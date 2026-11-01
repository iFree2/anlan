"""Scoped P13 ECS deployment with backup, additive migration and maintenance recovery."""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path("/opt/anlan2")
OLD = ROOT / "releases/p12-audit-only-20261025"
NEW = ROOT / "releases/p13-preflight-20261101"
MAINTENANCE = ROOT / "releases/p12-maintenance-20261025"
SHARED = ROOT / "shared"
CONFIG = SHARED / "console.json"
BACKUP = SHARED / "before-p13-preflight-20261101"
PRIVATE = SHARED / "p13-preflight-20261101"
DROPIN = Path("/etc/systemd/system/anlan2-console.service.d/p13-pythonpath.conf")
REQUIRED_WHEEL = {
    "anlan/interfaces/preflight_routes.py",
    "anlan/sql/019_preflight_bindings.sql",
    "anlan/sql/020_preflight_checks.sql",
    "anlan/interfaces/console/assets/app.js",
}
P13_WORKERS = {
    "worker-p13-normal": "active",
    "worker-p13-alert": "suspended",
}
P13_AREAS = {
    "area-p13-normal": "normal",
    "area-p13-restricted": "restricted",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def harness():
    spec = importlib.util.spec_from_file_location(
        "p12_release", "/opt/anlan2/release-collaboration-20261025.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.NEW = NEW
    return module


def require_fixed_path(path):
    allowed = {OLD, NEW, MAINTENANCE}
    if Path(path) not in allowed:
        raise ValueError("Deployment path is not one of the fixed P13 release paths")
    return Path(path)


def _collaboration_participants(config):
    roles = {
        grant.get("collaboration_role"): grant["identity"]
        for grant in config.get("tokens", [])
        if grant.get("collaboration_role") in {"applicant", "safety_manager"}
    }
    require(set(roles) == {"applicant", "safety_manager"}, "Applicant and manager required")
    require(
        roles["applicant"]["tenant_id"] == roles["safety_manager"]["tenant_id"],
        "Collaboration identities must share a tenant",
    )
    require(
        roles["applicant"]["user_id"] != roles["safety_manager"]["user_id"],
        "Collaboration identities must be distinct",
    )
    return roles


def p13_catalog(tenant_id):
    return {
        "tenant_id": tenant_id,
        "workers": [
            {
                "worker_id": "worker-p13-normal",
                "label": "SYNTHETIC 正常作业人员",
                "qualification_types": [
                    {"qualification_type": "welding", "label": "SYNTHETIC 焊接资质"}
                ],
            },
            {
                "worker_id": "worker-p13-alert",
                "label": "SYNTHETIC 资质异常人员",
                "qualification_types": [
                    {"qualification_type": "welding", "label": "SYNTHETIC 焊接资质"}
                ],
            },
        ],
        "areas": [
            {"area_id": "area-p13-normal", "label": "SYNTHETIC 正常区域"},
            {"area_id": "area-p13-restricted", "label": "SYNTHETIC 受限区域"},
        ],
    }


def dual_config(old, facts_dir, access_document):
    result = copy.deepcopy(old)
    roles = _collaboration_participants(result)
    tenant_id = roles["applicant"]["tenant_id"]
    result["facts_dir"] = str(facts_dir)
    result["precheck_catalogs"] = [
        item for item in result.get("precheck_catalogs", [])
        if item.get("tenant_id") != tenant_id
    ] + [p13_catalog(tenant_id)]
    # Validate object IDs are intentionally distinct metadata, not inferred from text.
    require(
        set(P13_WORKERS).isdisjoint({record["user_id"] for record in access_document["records"]}),
        "Worker/area IDs and user IDs must remain separate",
    )
    return result


def _append_unique(values, additions):
    result = list(values)
    for value in additions:
        if value not in result:
            result.append(value)
    return result


def merge_facts(access_document, fixtures, actor_user_ids, tenant_id):
    result = {"access.json": copy.deepcopy(access_document)}
    for name, document in fixtures.items():
        result[name] = copy.deepcopy(document)
    records = result["access.json"].setdefault("records", [])
    for user_id in actor_user_ids:
        record = next(
            (
                item
                for item in records
                if item.get("tenant_id") == tenant_id and item.get("user_id") == user_id
            ),
            None,
        )
        if record is None:
            record = {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "worker_ids": [],
                "area_ids": [],
            }
            records.append(record)
        record["worker_ids"] = _append_unique(record.get("worker_ids", []), P13_WORKERS)
        record["area_ids"] = _append_unique(record.get("area_ids", []), P13_AREAS)
    return result


def p13_fixtures(tenant_id):
    timestamp = {
        "observed_at": "2026-09-22T03:55:00Z",
        "valid_from": "2026-09-22T03:00:00Z",
        "valid_until": "2026-09-22T05:00:00Z",
    }
    qualifications = {
        "data_origin": "SYNTHETIC",
        "version": "p13-ecs-20261101",
        "records": [
            {
                "tenant_id": tenant_id,
                "record_id": "qualification-p13-" + worker_id,
                "object_id": worker_id,
                "qualification_type": "welding",
                "status": status,
                **timestamp,
            }
            for worker_id, status in P13_WORKERS.items()
        ],
    }
    areas = {
        "data_origin": "SYNTHETIC",
        "version": "p13-ecs-20261101",
        "records": [
            {
                "tenant_id": tenant_id,
                "record_id": "area-p13-" + area_id.removeprefix("area-p13-"),
                "object_id": area_id,
                "status": status,
                **timestamp,
            }
            for area_id, status in P13_AREAS.items()
        ],
    }
    return {"qualifications.json": qualifications, "areas.json": areas}


def p13_knowledge(user_ids):
    return {
        "data_origin": "SYNTHETIC",
        "doc_id": "p13-preflight-hot-work-ecs-v1",
        "version": 1,
        "title": "合成动火作业前依据",
        "source": "synthetic-p13-policy/preflight",
        "valid_from": "2026-09-22T03:00:00Z",
        "valid_until": "2026-09-23T00:00:00Z",
        "allowed_users": list(user_ids),
        "paragraphs": [
            "SYNTHETIC：作业前先核对已确认作业人员的焊接资质、当前区域状态和适用规程。"
            "安全人员必须明确选择实际采用的引用；材料核查完成不代表作业批准或开工授权。"
        ],
    }


def validate_wheel(path, expected_sha=None):
    with Path(path).open("rb") as stream:
        content = stream.read()
    if expected_sha:
        require(digest(content) == expected_sha, "Wheel SHA-256 mismatch")
    with zipfile.ZipFile(Path(path)) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED_WHEEL - names)
        require(not missing, "Wheel is missing P13 preflight resources")
        for item in archive.infolist():
            member = PurePosixPath(item.filename)
            require(
                not member.is_absolute()
                and ".." not in member.parts
                and "\\" not in item.filename
                and ":" not in item.filename
                and (item.external_attr >> 16) & 0o170000 != 0o120000,
                "Unsafe wheel entry",
            )
        require(
            "作业前依据" in archive.read("anlan/interfaces/console/assets/app.js").decode(
                "utf-8"
            ),
            "Wheel console is missing P13 precheck presentation",
        )
    return digest(content)


def _database_env(h):
    from psycopg.conninfo import conninfo_to_dict

    env = h.environment()
    db = conninfo_to_dict(env["ANLAN_DATABASE_URL"])
    return env | {
        key: db[field]
        for key, field in (
            ("PGHOST", "host"),
            ("PGPORT", "port"),
            ("PGUSER", "user"),
            ("PGPASSWORD", "password"),
            ("PGDATABASE", "dbname"),
        )
        if field in db
    }


def _copy_private(source, destination):
    shutil.copy2(source, destination)
    destination.chmod(0o600)


def _write_private_json(path, document):
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        _chown_application_user(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _chown_application_user(path):
    if not hasattr(os, "chown"):
        return
    import pwd

    user = pwd.getpwnam("anlan2")
    os.chown(path, user.pw_uid, user.pw_gid)


def _backup_database(h, backup):
    dump_bin = next(
        (path for path in (Path("/usr/pgsql-13/bin/pg_dump"), Path("/usr/bin/pg_dump"))
         if path.is_file()),
        None,
    )
    require(dump_bin is not None, "Database backup utility missing")
    dump = backup / "database.dump"
    h.command(
        str(dump_bin),
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file=" + str(dump),
        env=_database_env(h),
    )
    dump.chmod(0o600)
    h.command(str(dump_bin.with_name("pg_restore")), "--list", str(dump))
    return digest(dump.read_bytes())


def inspect():
    h = harness()
    config = json.loads(CONFIG.read_text())
    roles = _collaboration_participants(config)
    snapshot = h.snapshot()
    snapshot.pop("rows")
    return {
        "status": "inspected",
        "service": h.command("systemctl", "is-active", "anlan2-console"),
        "current": str((h.ROOT / "current").resolve()),
        "config_sha256": digest(CONFIG.read_bytes()),
        "facts_dir": config.get("facts_dir"),
        "model_mode": config.get("model_mode"),
        "collaboration_roles": sorted(roles),
        "precheck_catalogs": len(config.get("precheck_catalogs", [])),
        "snapshot": snapshot,
    }


def prepare(wheel, expected_sha):
    h = harness()
    wheel = Path(wheel)
    require(os.geteuid() == 0, "Scoped root deployment required")
    require((h.ROOT / "current").resolve() == OLD, "Unexpected active release")
    require(not BACKUP.exists() and not PRIVATE.exists() and not NEW.exists(),
            "P13 release/backup already prepared")
    require(MAINTENANCE.is_dir(), "Maintenance application missing")
    wheel_sha = validate_wheel(wheel, expected_sha)
    before = h.snapshot()
    h.require_quiescent(before["pending"])
    h.wait_ready(json.loads(CONFIG.read_text()))

    BACKUP.mkdir(mode=0o700)
    for name in ("app.env", "console.json"):
        _copy_private(SHARED / name, BACKUP / name)
    h.private_json(
        BACKUP / "recovery.json",
        {
            "old_release": str(OLD),
            "forward_release": str(NEW),
            "maintenance": str(MAINTENANCE),
            "policy": "Never restore the database or run the legacy write API after P13.",
        },
    )
    dump_sha = _backup_database(h, BACKUP)
    require(h.snapshot()["rows"] == before["rows"], "Data changed during backup")

    NEW.mkdir(mode=0o755)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(NEW / "app")
    shutil.copy2(wheel, NEW / wheel.name)
    for name in ("venv", "examples"):
        (NEW / name).symlink_to((OLD / name).resolve(), target_is_directory=True)

    old_config = json.loads(CONFIG.read_text())
    roles = _collaboration_participants(old_config)
    tenant_id = roles["applicant"]["tenant_id"]
    actor_ids = [roles["applicant"]["user_id"], roles["safety_manager"]["user_id"]]
    old_facts = Path(old_config["facts_dir"])
    PRIVATE.mkdir(mode=0o700)
    _chown_application_user(PRIVATE)
    facts = PRIVATE / "facts"
    facts.mkdir(mode=0o700)
    _chown_application_user(facts)
    for path in old_facts.glob("*.json"):
        shutil.copy2(path, facts / path.name)
    facts_document = merge_facts(
        json.loads((old_facts / "access.json").read_text()),
        p13_fixtures(tenant_id),
        actor_ids,
        tenant_id,
    )
    for name, document in facts_document.items():
        _write_private_json(facts / name, document)
    config = dual_config(old_config, facts, facts_document["access.json"])
    h.private_json(PRIVATE / "service.json", config)

    probe_env = h.environment() | {"PYTHONPATH": str(NEW / "app")}
    h.command(
        str(NEW / "venv/bin/python"),
        "-c",
        "from anlan.interfaces.service_config import ServiceConfig;"
        "ServiceConfig.from_file(" + repr(str(PRIVATE / "service.json")) + ")",
        env=probe_env,
    )
    knowledge = p13_knowledge(actor_ids)
    h.command(
        str(NEW / "venv/bin/python"),
        "-c",
        (
            "import json,os\n"
            "from datetime import datetime\n"
            "from pathlib import Path\n"
            "from anlan.common.models import Identity\n"
            "from anlan.knowledge.embeddings import LocalEmbeddings\n"
            "from anlan.knowledge.store import KnowledgeStore\n"
            "from anlan.infrastructure.db import database_url\n"
            "cfg=json.loads(Path(os.environ['P13_CONFIG']).read_text())\n"
            "roles={g['collaboration_role']:g['identity'] for g in cfg['tokens'] "
            "if g.get('collaboration_role')}\n"
            "async def main():\n"
            "    emb=await LocalEmbeddings.create(Path(cfg['embeddings_cache']))\n"
            "    store=KnowledgeStore(database_url(),emb,clock=lambda:datetime.fromisoformat("
            "cfg['as_of']))\n"
            "    await store.initialize()\n"
            "    owner=Identity(tenant_id=roles['applicant']['tenant_id'],"
            "user_id=roles['applicant']['user_id'])\n"
            "    await store.ingest(owner,json.loads(os.environ['P13_KNOWLEDGE']))\n"
            "import asyncio\n"
            "asyncio.run(main(),loop_factory=asyncio.SelectorEventLoop)\n"
        ),
        env=probe_env
        | {
            "P13_CONFIG": str(PRIVATE / "service.json"),
            "P13_KNOWLEDGE": json.dumps(knowledge, ensure_ascii=False),
        },
    )
    after = h.snapshot()
    require(h.preserved(before, after), "Existing rows changed during preparation")
    require(before["ledger"] == after["ledger"], "Unexpected model requests")
    manifest = {
        "status": "prepared",
        "old_release": str(OLD),
        "new_release": str(NEW),
        "maintenance": str(MAINTENANCE),
        "wheel_sha256": wheel_sha,
        "database_dump_sha256": dump_sha,
        "config_sha256": digest(CONFIG.read_bytes()),
        "old_config_sha256": digest((BACKUP / "console.json").read_bytes()),
        "before_counts": before["counts"],
        "ledger_before": before["ledger"],
        "p13_knowledge_doc": knowledge["doc_id"],
        "new_model_requests": 0,
    }
    h.private_json(NEW / "rollout.json", manifest)
    return manifest


def _write_dropin():
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    DROPIN.write_text(
        "[Service]\nEnvironment=PYTHONPATH=/opt/anlan2/current/app\n",
        encoding="utf-8",
    )


def _replace_config(h, config):
    temporary = SHARED / ("console.p13-" + secrets.token_hex(8))
    h.private_json(temporary, config)
    os.replace(temporary, CONFIG)


def _precheck_read_probe(h, config):
    roles = _collaboration_participants(config)
    grants = {
        grant["collaboration_role"]: grant["token"]
        for grant in config["tokens"]
        if grant.get("collaboration_role")
    }
    tenant_id = roles["safety_manager"]["tenant_id"]
    import psycopg

    with psycopg.connect(h.environment()["ANLAN_DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT task_id FROM anlan_v2.collaboration_applications "
            "WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
    require(row is not None, "No existing application for authenticated read probe")
    status, body = h.request(
        f"/collaboration/applications/{row[0]}/prechecks",
        grants["safety_manager"],
    )
    require(status == 200 and "precheck" not in body, "P13 authenticated read failed")
    require(
        body.get("legacy_completed") is True
        or body.get("required") is True
        or body.get("status") in {
            "unbound", "not_checked", "queued", "running", "ready", "gap", "failed", "stale"
        },
        "P13 precheck projection missing",
    )
    return {"task_id": row[0], "status": body.get("status")}


def _verify_active(h, config):
    infos = h.wait_ready(config)
    require(h.request("/console/api/info")[0] == 401, "Anonymous console access not denied")
    asset = urllib.request.urlopen(
        "http://127.0.0.1:8018/console/assets/app.js", timeout=10
    ).read().decode("utf-8")
    require(
        "作业前依据" in asset
        and "object-catalog" in asset
        and "冻结采用引用并确认" in asset,
        "Serving console is not the P13 build",
    )
    probe = _precheck_read_probe(h, config)
    import psycopg

    with psycopg.connect(h.environment()["ANLAN_DATABASE_URL"]) as conn:
        migrations = {
            row[0]
            for row in conn.execute(
                "SELECT version FROM anlan_v2.anlan_schema_migrations WHERE version IN (19,20)"
            )
        }
    require(migrations == {19, 20}, "P13 migrations incomplete")
    return infos, probe, sorted(migrations)


def activate():
    h = harness()
    require(os.geteuid() == 0, "Scoped root deployment required")
    require((h.ROOT / "current").resolve() == OLD, "Unexpected active release")
    manifest = json.loads((NEW / "rollout.json").read_text())
    require(manifest.get("status") == "prepared", "Prepared manifest missing")
    require(digest((BACKUP / "database.dump").read_bytes()) == manifest["database_dump_sha256"],
            "Database backup changed")
    require(digest(CONFIG.read_bytes()) == manifest["config_sha256"],
            "Configuration changed after preparation")
    config = json.loads((PRIVATE / "service.json").read_text())
    before = h.snapshot()
    h.require_quiescent(before["pending"])
    _write_dropin()
    try:
        h.command("systemctl", "daemon-reload")
        h.command("systemctl", "stop", "anlan2-console")
        _replace_config(h, config)
        h.switch_release(NEW)
        h.command("systemctl", "start", "anlan2-console")
        infos, probe, migrations = _verify_active(h, config)
        after = h.snapshot()
        require(h.preserved(before, after), "Existing business or audit rows changed")
        require(before["ledger"] == after["ledger"], "Unexpected model request")
    except Exception:
        h.rollback()
        raise RuntimeError("Activation failed; maintenance remains active") from None
    report = {
        **manifest,
        "status": "activated",
        "current": str(NEW),
        "service_pid": h.command("systemctl", "show", "-p", "MainPID", "--value",
                                 "anlan2-console"),
        "roles": [
            {
                "role": item.get("collaboration_role"),
                "model_mode": info.get("model_mode"),
            }
            for item, info in zip(config["tokens"], infos, strict=True)
        ],
        "anonymous_status": 401,
        "p13_console_asset": True,
        "precheck_read_probe": probe,
        "migrations": sorted(migrations),
        "old_rows_preserved": True,
        "ledger_unchanged": True,
        "new_model_requests": 0,
    }
    (NEW / "rollout.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def rollback():
    h = harness()
    return h.rollback()


def forward():
    h = harness()
    require(os.geteuid() == 0, "Scoped root deployment required")
    require((h.ROOT / "current").resolve() == MAINTENANCE, "Maintenance mode required")
    config = json.loads((PRIVATE / "service.json").read_text())
    h.command("systemctl", "stop", "anlan2-console")
    _replace_config(h, config)
    h.switch_release(NEW)
    h.command("systemctl", "start", "anlan2-console")
    try:
        infos, probe, migrations = _verify_active(h, config)
    except Exception:
        h.rollback()
        raise RuntimeError("Forward recovery failed; maintenance remains active") from None
    manifest = json.loads((NEW / "rollout.json").read_text())
    report = {
        **manifest,
        "status": "activated",
        "current": str(NEW),
        "service_pid": h.command("systemctl", "show", "-p", "MainPID", "--value",
                                 "anlan2-console"),
        "roles": [
            {
                "role": item.get("collaboration_role"),
                "model_mode": info.get("model_mode"),
            }
            for item, info in zip(config["tokens"], infos, strict=True)
        ],
        "anonymous_status": 401,
        "p13_console_asset": True,
        "precheck_read_probe": probe,
        "migrations": migrations,
        "old_rows_preserved_during_forward": True,
        "recovered_from_maintenance": True,
        "new_model_requests": 0,
    }
    (NEW / "rollout.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "prepare", "activate", "rollback",
                                          "forward"])
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if args.wheel is None or not args.sha256:
                parser.error("prepare requires --wheel and --sha256")
            result = prepare(args.wheel, args.sha256)
        else:
            result = {
                "inspect": inspect,
                "activate": activate,
                "rollback": rollback,
                "forward": forward,
            }[args.action]()
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "details": "Private output hidden",
        }))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
