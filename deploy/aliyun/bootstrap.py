"""Install only this synthetic console's isolated database, config and systemd service.

Run as root on the inspected server after the wheel, locked dependencies and
pgvector have been prepared. Administrative passwords are never required here:
PostgreSQL administration uses the existing local postgres account over SSH.
"""
import asyncio
import json
import os
import pwd
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path("/opt/anlan2")
RELEASE = ROOT / "releases/p8-console-20261007"
SHARED = ROOT / "shared"
DATABASE = "anlan2_console"
ROLE = "anlan2_console_app"


def postgres(sql):
    run = subprocess.run(
        ["runuser", "-u", "postgres", "--", "psql", "-X", "-A", "-t",
         "-v", "ON_ERROR_STOP=1", "-d", "postgres"],
        input=sql, text=True, capture_output=True, cwd="/tmp",
    )
    if run.returncode:
        raise RuntimeError("Isolated PostgreSQL bootstrap failed; SQL/credentials hidden")
    return run.stdout.strip()


def private_write(path, value, *, owner=None):
    with path.open("x", encoding="utf-8") as file:
        file.write(value)
    path.chmod(0o600)
    if owner:
        os.chown(path, owner.pw_uid, owner.pw_gid)


def setup_database():
    env_path = SHARED / "app.env"
    if not env_path.exists():
        occupied = postgres(
            f"SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='{DATABASE}') "
            f"OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{ROLE}');"
        )
        if occupied != "f":
            raise RuntimeError("Target database or role already exists; no overwrite permitted")
        password = secrets.token_hex(32)
        postgres(
            "SET log_statement='none'; SET log_min_duration_statement=-1; "
            "SET log_duration=off; SET log_min_error_statement='panic';\n"
            f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"PASSWORD '{password}';\nCREATE DATABASE {DATABASE} OWNER {ROLE};\n"
        )
        private_write(env_path, "ANLAN_DATABASE_URL=postgresql://" + ROLE + ":" + password
                      + "@127.0.0.1:5432/" + DATABASE + "\n")
    os.environ["ANLAN_DATABASE_URL"] = env_path.read_text().strip().split("=", 1)[1]
    # Existing loopback rules use ident. Add only our database/role exception.
    rule = f"host {DATABASE} {ROLE} 127.0.0.1/32 scram-sha-256"
    hba = Path(postgres("SHOW hba_file;"))
    content = hba.read_text()
    if rule not in content.splitlines():
        backup = SHARED / "pg_hba.before-console"
        if not backup.exists():
            private_write(backup, content)
        password = urlsplit(os.environ["ANLAN_DATABASE_URL"]).password
        postgres(
            "SET log_statement='none'; SET log_min_duration_statement=-1; "
            "SET log_duration=off; SET log_min_error_statement='panic'; "
            "SET password_encryption='scram-sha-256';\n"
            f"ALTER ROLE {ROLE} PASSWORD '{password}';\n"
        )
        hba.write_text("# Anlan synthetic console localhost-only\n" + rule + "\n" + content)
        assert postgres("SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;") == "0"
        assert postgres("SELECT pg_reload_conf();") == "t"
    postgres(f"\\connect {DATABASE}\nCREATE EXTENSION IF NOT EXISTS vector;\n")


async def prepare_budget():
    from psycopg import AsyncConnection
    from psycopg.types.json import Jsonb

    from anlan.infrastructure.budget import BudgetLedger
    from anlan.infrastructure.db import conninfo, database_url
    from anlan.infrastructure.postgres import initialize_database

    await initialize_database(database_url())
    ledger = BudgetLedger(database_url())
    await ledger.initialize()
    data = json.loads((RELEASE / "model-budget.json").read_text())
    auth = data["authorization"]
    assert auth["authorization_id"] == ledger.authorization_id
    assert auth["total_limit"] == 100 and auth["package_limit"] == 10
    assert len(data["attempts"]) == 46 and all(r["status"] != "reserved" for r in data["attempts"])
    async with await AsyncConnection.connect(conninfo(database_url())) as conn:
        await conn.execute(
            "SELECT authorization_id FROM anlan_v2.model_budget_authorizations "
            "WHERE authorization_id=%s FOR UPDATE", (ledger.authorization_id,),
        )
        count = (await (await conn.execute(
            "SELECT count(*) FROM anlan_v2.model_budget_attempts WHERE authorization_id=%s",
            (ledger.authorization_id,),
        )).fetchone())[0]
        if count not in (0, 46):
            raise RuntimeError("Existing remote model ledger differs; no merge/reset permitted")
        await conn.execute(
            "UPDATE anlan_v2.model_budget_authorizations SET created_at=%s "
            "WHERE authorization_id=%s", (auth["created_at"], ledger.authorization_id),
        )
        for row in data["attempts"]:
            await conn.execute(
                "INSERT INTO anlan_v2.model_budget_attempts "
                "(attempt_id,authorization_id,work_package,run_id,status,usage,error,"
                "reserved_at,finished_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (attempt_id) DO NOTHING",
                (row["attempt_id"], row["authorization_id"], row["work_package"], row["run_id"],
                 row["status"], Jsonb(row["usage"]) if row["usage"] is not None else None,
                 row["error"], row["reserved_at"], row["finished_at"]),
            )
    snapshot = await ledger.snapshot()
    assert snapshot["total_reserved"] == 46 and snapshot["status_counts"]["reserved"] == 0
    return {"total_reserved": 46, "new_requests": 0}


def setup_config(owner):
    path = SHARED / "console.json"
    if not path.exists():
        access = json.loads((SHARED / "client-access.json").read_text())
        refs = json.loads((RELEASE / "examples/synthetic/perception-v1/refs.json").read_text())
        access.update(
            as_of="2026-09-22T04:00:00+00:00", sources=[],
            facts_dir=str(RELEASE / "examples/synthetic/perception-v1/facts"),
            embeddings_cache=str(SHARED / "embeddings"),
            console_profiles=[{"identity": access["tokens"][0]["identity"], "references": refs}],
        )
        private_write(path, json.dumps(access, ensure_ascii=False), owner=owner)
    (SHARED / "client-access.json").chmod(0o600)


async def seed_knowledge():
    from datetime import datetime

    from anlan.common.models import Identity
    from anlan.infrastructure.db import database_url
    from anlan.knowledge.embeddings import LocalEmbeddings
    from anlan.knowledge.store import KnowledgeStore

    config = json.loads((SHARED / "console.json").read_text())
    store = KnowledgeStore(
        database_url(), await LocalEmbeddings.create(SHARED / "embeddings"),
        clock=lambda: datetime.fromisoformat(config["as_of"]),
    )
    await store.initialize()
    identity = Identity.model_validate(config["tokens"][0]["identity"])
    data = json.loads((RELEASE / "examples/synthetic/perception-v1/knowledge.json").read_text())
    for document in data["documents"]:
        await store.ingest(identity, document)
    return len(data["documents"])


def main():
    if os.geteuid() != 0 or not RELEASE.is_dir():
        raise RuntimeError("Expected the prepared isolated release and root administration")
    setup_database()
    try:
        owner = pwd.getpwnam("anlan2")
    except KeyError:
        subprocess.run(["useradd", "--system", "--home-dir", str(ROOT),
                        "--shell", "/sbin/nologin", "anlan2"], check=True)
        owner = pwd.getpwnam("anlan2")
    setup_config(owner)
    report = {"database": DATABASE, "process_user": "anlan2",
              "budget": asyncio.run(prepare_budget()),
              "knowledge_documents": asyncio.run(seed_knowledge())}
    current = ROOT / "current"
    if not current.exists():
        current.symlink_to(RELEASE, target_is_directory=True)
    elif current.resolve() != RELEASE.resolve():
        raise RuntimeError("Current release differs; explicit rollout required")
    unit = """[Unit]
Description=Anlan synthetic learning console
After=network.target postgresql.service

[Service]
Type=simple
User=anlan2
Group=anlan2
WorkingDirectory=/opt/anlan2/current
EnvironmentFile=/opt/anlan2/shared/app.env
Environment=PYTHONUNBUFFERED=1
Environment=OMP_NUM_THREADS=2
ExecStart=/opt/anlan2/current/venv/bin/python -m anlan.interfaces.serve \
    --config /opt/anlan2/shared/console.json --port 8018 --root-path /anlan
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/anlan2/shared
UMask=0077

[Install]
WantedBy=multi-user.target
"""
    target = Path("/etc/systemd/system/anlan2-console.service")
    if not target.exists():
        target.write_text(unit)
    elif target.read_text() != unit:
        raise RuntimeError("Existing service differs; no overwrite permitted")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "anlan2-console"], check=True)
    report["status"] = "installed"
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "details": "Deployment error; credentials and SQL hidden"}))
        raise SystemExit(1) from None
