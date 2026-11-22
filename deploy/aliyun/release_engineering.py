"""Fixed-target engineering release; zero business writes and no implicit MCP activation."""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

ROOT = Path("/opt/anlan2")
BASE = ROOT / "releases/business-query-20261117"
NEW = ROOT / "releases/engineering-20261119"
MAINTENANCE = ROOT / "releases/p12-maintenance-20261025"
SHARED = ROOT / "shared"
BACKUP = SHARED / "before-engineering-20261119"
CONFIG, ENV = SHARED / "console.json", SHARED / "app.env"
WHEEL_NAME = "anlan-0.1.0-py3-none-any.whl"
WHEEL_SHA = "9b8f72e5d26b58d3f40af1d797b8d455952fce728d2c655218a3d93c44b2d901"
CONFIG_SHA = "7b03174b784e69e85d10f057df46c690bab077ebdbfedcb88d0e0d8d7ec0deaf"
HELPERS = {
    "release-business-query-20261117.py": (
        "c7a78de56d70339b08ced0a9c8a2f204bbc252a36206b3d0cc6b6cc7fa2d32ae"
    ),
    "release-collaboration-20261025.py": (
        "3ef15464f65296c2e53320fa3b6d04f6f7da060fc0c6e96d32cf9db8ee6b31c8"
    ),
    "release-preflight-20261101.py": (
        "ce25f4231fa7cb1d676590b389b1a9006c0535700cfea8234a40cb25b50c68bc"
    ),
}
EXPECTED_DEPENDENCIES = {
    "mcp": "1.30.0",
    "pydantic": "2.13.5",
    "fastapi": "0.141.1",
    "psycopg": "3.3.6",
    "langgraph": "1.2.11",
    "httpx": "0.28.1",
}
REQUIRED = {
    "anlan/business_query/service.py",
    "anlan/business_query/contracts.py",
    "anlan/infrastructure/business_queries.py",
    "anlan/sql/021_business_queries.sql",
    "anlan/tools/registry.py",
    "anlan/tools/policy.py",
    "anlan/tools/executor.py",
    "anlan/tools/dynamic_mcp/execution.py",
    "anlan/tools/dynamic_mcp/registry.py",
    "anlan/knowledge/parsing/text.py",
    "anlan/knowledge/retrieval/service.py",
    "anlan/evaluation/knowledge_runner.py",
    "anlan/workflows/external_inquiry.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_helper(path, expected, name):
    require(digest(Path(path).read_bytes()) == expected, "Unexpected helper fingerprint")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def harness():
    # Check every nested import before loading any previous deployment executable.
    for name, expected in HELPERS.items():
        require(digest((ROOT / name).read_bytes()) == expected, "Unexpected helper fingerprint")
    h = load_helper(
        ROOT / "release-collaboration-20261025.py",
        HELPERS["release-collaboration-20261025.py"],
        "engineering_harness",
    )
    h.NEW = NEW
    return h


def query_helper():
    return load_helper(
        ROOT / "release-business-query-20261117.py",
        HELPERS["release-business-query-20261117.py"],
        "engineering_query",
    )


def systemd_metadata(h):
    return query_helper().systemd_metadata(h)


def migration_versions(h):
    return query_helper().migration_versions(h)


def snapshot(h):
    import psycopg

    before = h.snapshot()
    with psycopg.connect(h.environment()["ANLAN_DATABASE_URL"]) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        before["pending"]["precheck_jobs"] = conn.execute(
            "SELECT count(*) FROM anlan_v2.precheck_jobs WHERE status IN ('queued','running')"
        ).fetchone()[0]
        before["pending"]["precheck_attempts"] = conn.execute(
            "SELECT count(*) FROM anlan_v2.precheck_attempts WHERE status='running'"
        ).fetchone()[0]
    return before


def assert_preserved(before, after):
    for name in ("rows", "ledger", "packages", "statuses"):
        require(before[name] == after[name], "Existing data or model ledger changed")


def quiescent(state):
    require(not any(state["pending"].values()), "Unfinished operations or prechecks")


def validate_wheel(path, expected_sha):
    require(digest(Path(path).read_bytes()) == expected_sha, "Wheel SHA-256 mismatch")
    with zipfile.ZipFile(path) as archive:
        names = set()
        for item in archive.infolist():
            p = PurePosixPath(item.filename)
            require(
                not p.is_absolute()
                and ".." not in p.parts
                and "\\" not in item.filename
                and ":" not in item.filename
                and (item.external_attr >> 16) & 0o170000 != 0o120000,
                "Unsafe wheel entry",
            )
            require(item.filename not in names, "Unsafe duplicate wheel entry")
            names.add(item.filename)
        require(REQUIRED <= names, "Missing query or engineering resources")
    return expected_sha


def verify_dependencies(h, release):
    code = (
        "import json;from importlib.metadata import version;"
        f"print(json.dumps({{k:version(k) for k in {list(EXPECTED_DEPENDENCIES)!r}}}))"
    )
    versions = json.loads(
        h.command(str(release / "venv/bin/python"), "-c", code, env=h.environment())
    )
    require(versions == EXPECTED_DEPENDENCIES, "Installed dependency versions differ")


def import_probe(h, release):
    code = r"""import importlib,json,pkgutil,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import anlan
modules=[]
for item in pkgutil.walk_packages(anlan.__path__,'anlan.'):
 if item.name.endswith('.__main__'): continue
 m=importlib.import_module(item.name)
 if not Path(m.__file__).is_relative_to(Path(sys.argv[1])): raise ValueError('Wrong module root')
 modules.append(item.name)
from anlan.knowledge.parsing.text import parse_txt
from anlan.knowledge.parsing.contracts import SourceCandidate,TxtIngestMetadata
d=parse_txt(b'SYNTHETIC engineering probe\r\n',filename='probe.txt',
 metadata=TxtIngestMetadata(tenant_id='synthetic-probe',logical_document_id='p',document_version_id='1',generation=1,title='SYNTHETIC'),
 candidate=SourceCandidate(schema_version='knowledge.source-candidate.v1',candidate_id='p',data_origin='SYNTHETIC',source_url='synthetic://probe/input',review_state='candidate'))
assert d.published is False and d.document.blocks[0].source_text.endswith('\r\n')
from anlan.tools.dynamic_mcp.catalog import expected_schemas
expected_schemas('equipment.asset.query')
print(json.dumps({'modules':len(modules),'txt_draft_unpublished':True,'mcp_schema_imported':True}))
"""
    return json.loads(
        h.command(
            str(release / "venv/bin/python"), "-c", code, str(release / "app"), env=h.environment()
        )
    )


def write_report(path, document):
    h = harness()
    temporary = path.with_name(path.name + ".pending-" + uuid4().hex)
    h.private_json(temporary, document)
    os.replace(temporary, path)


def fingerprints(h):
    return dict(
        config_sha256=digest(CONFIG.read_bytes()),
        env_sha256=digest(ENV.read_bytes()),
        systemd_sha256=systemd_metadata(h)[0],
    )


def verify_fingerprints(h, expected, *, backup=False):
    current = fingerprints(h)
    require(
        current == {key: expected[key] for key in current},
        "Configuration or systemd fingerprint changed",
    )
    if backup:
        require(
            digest((BACKUP / "console.json").read_bytes()) == expected["config_sha256"]
            and digest((BACKUP / "app.env").read_bytes()) == expected["env_sha256"],
            "Backup configuration fingerprint changed",
        )
        unit = json.loads((BACKUP / "systemd.json").read_text())
        require(
            digest(json.dumps(unit, sort_keys=True).encode()) == expected["systemd_sha256"],
            "Backup systemd fingerprint changed",
        )


def prepare(wheel, source_commit):
    h = harness()
    require(os.geteuid() == 0, "Scoped root deployment required")
    require(re.fullmatch("[0-9a-f]{40}", source_commit) is not None, "Invalid source commit")
    require((ROOT / "current").resolve() == BASE, "Unexpected active release")
    require(not NEW.exists() and not BACKUP.exists(), "Already prepared; inspect state")
    require(MAINTENANCE.is_dir(), "Maintenance application missing")
    require(digest(CONFIG.read_bytes()) == CONFIG_SHA, "Unexpected trusted configuration")
    wheel = Path(wheel)
    validate_wheel(wheel, WHEEL_SHA)
    q = query_helper()
    require(
        q.dependency_signature(wheel) == q.dependency_signature(BASE / WHEEL_NAME),
        "Dependency declarations differ",
    )
    verify_dependencies(h, BASE)
    versions = migration_versions(h)
    require(
        {17, 18, 19, 20, 21} <= set(versions) and not {22, 23} & set(versions),
        "Unexpected migration state",
    )
    before = snapshot(h)
    quiescent(before)
    h.wait_ready(json.loads(CONFIG.read_text()))
    unit_sha, unit = systemd_metadata(h)
    initial = dict(
        config_sha256=digest(CONFIG.read_bytes()),
        env_sha256=digest(ENV.read_bytes()),
        systemd_sha256=unit_sha,
    )
    BACKUP.mkdir(mode=0o700)
    for name in ("console.json", "app.env"):
        shutil.copy2(SHARED / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    h.private_json(BACKUP / "systemd.json", unit)
    h.private_json(BACKUP / "before.json", before)
    h.private_json(
        BACKUP / "recovery.json",
        {
            "base": str(BASE),
            "forward": str(NEW),
            "maintenance": str(MAINTENANCE),
            "database_restore_permitted": False,
        },
    )
    p13 = load_helper(
        ROOT / "release-preflight-20261101.py",
        HELPERS["release-preflight-20261101.py"],
        "engineering_backup",
    )
    backup_sha = p13._backup_database(h, BACKUP)
    verify_fingerprints(h, initial, backup=True)
    after = snapshot(h)
    quiescent(after)
    assert_preserved(before, after)
    NEW.mkdir(mode=0o755)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(NEW / "app")
    shutil.copy2(wheel, NEW / WHEEL_NAME)
    for name in ("venv", "examples"):
        (NEW / name).symlink_to((BASE / name).resolve(), target_is_directory=True)
    verify_dependencies(h, NEW)
    probe = import_probe(h, NEW)
    verify_fingerprints(h, initial, backup=True)
    report = dict(
        status="prepared",
        base=str(BASE),
        new_release=str(NEW),
        source_commit=source_commit,
        wheel_sha256=WHEEL_SHA,
        database_dump_sha256=backup_sha,
        config_sha256=initial["config_sha256"],
        env_sha256=initial["env_sha256"],
        systemd_sha256=unit_sha,
        dependencies=EXPECTED_DEPENDENCIES,
        migrations_before=versions,
        before_counts=before["counts"],
        ledger_before=before["ledger"],
        import_probe=probe,
        new_model_requests=0,
    )
    write_report(NEW / "rollout.json", report)
    return report


def activation_gate(h, forward=False):
    require(os.geteuid() == 0, "Scoped root deployment required")
    require(
        (ROOT / "current").resolve() == (MAINTENANCE if forward else BASE),
        "Unexpected active release",
    )
    manifest = json.loads((NEW / "rollout.json").read_text())
    require(manifest.get("status") in {"prepared", "activated"}, "Prepared manifest missing")
    require(
        digest(CONFIG.read_bytes()) == manifest["config_sha256"]
        and digest(ENV.read_bytes()) == manifest["env_sha256"],
        "Configuration changed",
    )
    require(systemd_metadata(h)[0] == manifest["systemd_sha256"], "Systemd changed")
    require(
        digest((BACKUP / "database.dump").read_bytes()) == manifest["database_dump_sha256"],
        "Backup fingerprint changed",
    )
    validate_wheel(NEW / WHEEL_NAME, manifest["wheel_sha256"])
    verify_dependencies(h, NEW)
    require(migration_versions(h) == manifest["migrations_before"], "Migration set changed")
    verify_fingerprints(h, manifest, backup=True)
    if forward:
        recovery = json.loads((BACKUP / "recovery-current.json").read_text())
        name = recovery["snapshot"]
        require(
            re.fullmatch("maintenance-snapshot-[0-9a-f]{32}.json", name) is not None,
            "Invalid recovery snapshot path",
        )
        require(recovery.get("candidate") == str(NEW), "Recovery candidate mismatch")
        saved = BACKUP / name
        require(digest(saved.read_bytes()) == recovery["sha256"], "Recovery snapshot changed")
        before = json.loads(saved.read_text())
    else:
        before = json.loads((BACKUP / "before.json").read_text())
    current = snapshot(h)
    quiescent(current)
    assert_preserved(before, current)
    return manifest, before


def rollback(h=None):
    h = h or harness()
    h.rollback()
    h.wait_maintenance()
    require((ROOT / "current").resolve() == MAINTENANCE, "Maintenance release mismatch")
    state = snapshot(h)
    quiescent(state)
    saved = BACKUP / ("maintenance-snapshot-" + uuid4().hex + ".json")
    h.private_json(saved, state)
    recovery = dict(
        snapshot=saved.name,
        sha256=digest(saved.read_bytes()),
        candidate=str(NEW),
        status="maintenance_verified",
    )
    write_report(BACKUP / "recovery-current.json", recovery)
    return dict(
        status="maintenance_verified",
        database_preserved=True,
        recovery_snapshot_sha256=recovery["sha256"],
    )


def activate(forward=False):
    h = harness()
    manifest, before = activation_gate(h, forward)
    try:
        h.command("systemctl", "stop", "anlan2-console")
        stopped = snapshot(h)
        quiescent(stopped)
        assert_preserved(before, stopped)
        require(migration_versions(h) == manifest["migrations_before"], "Migration set changed")
        verify_fingerprints(h, manifest, backup=True)
        verify_dependencies(h, NEW)
        h.switch_release(NEW)
        h.command("systemctl", "start", "anlan2-console")
        verification = verify_active(h)
        after = snapshot(h)
        quiescent(after)
        assert_preserved(before, after)
        require(
            digest(CONFIG.read_bytes()) == manifest["config_sha256"]
            and digest(ENV.read_bytes()) == manifest["env_sha256"],
            "Configuration changed",
        )
        require(systemd_metadata(h)[0] == manifest["systemd_sha256"], "Systemd changed")
        report = dict(manifest, **verification)
        report.update(
            status="activated",
            forward_recovery=forward,
            preservation_baseline_counts=before["counts"],
            preservation_baseline_ledger=before["ledger"],
            current=str(NEW),
            service_pid=h.command(
                "systemctl", "show", "-p", "MainPID", "--value", "anlan2-console"
            ),
            old_rows_preserved=True,
            business_state_unchanged=True,
            ledger_after=after["ledger"],
            after_counts=after["counts"],
            ledger_unchanged=True,
            new_model_requests=0,
        )
        write_report(NEW / "rollout.json", report)
        return report
    except Exception:
        try:
            rollback(h)
        except Exception:
            raise RuntimeError(
                "Activation failed; recovery_failed; private output hidden"
            ) from None
        raise RuntimeError(
            "Activation failed; maintenance_verified; private output hidden"
        ) from None


def read_only_query_probe(h, config):
    import psycopg

    grants = config["tokens"]
    conversations = []
    query_types = set()
    with psycopg.connect(h.environment()["ANLAN_DATABASE_URL"]) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        for grant in grants:
            identity = grant["identity"]
            row = conn.execute(
                "SELECT c.conversation_id,count(*),array_agg(r.query_type) "
                "FROM anlan_v2.conversations c JOIN anlan_v2.conversation_messages m "
                "USING(conversation_id) JOIN anlan_v2.business_query_receipts r "
                "ON r.source_message_id=m.message_id WHERE c.tenant_id=%s AND c.user_id=%s "
                "GROUP BY c.conversation_id ORDER BY count(*) DESC LIMIT 1",
                (identity["tenant_id"], identity["user_id"]),
            ).fetchone()
            require(row is not None, "Existing query acceptance history missing")
            status, body = h.request("/conversations/" + row[0], grant["token"])
            require(status == 200 and body.get("messages"), "Existing query readback failed")
            conversations.append(row[0])
            query_types.update(row[2])
        require(
            {"application_status", "application_details", "process_guidance", "safety_knowledge"}
            <= query_types,
            "Saved query coverage missing",
        )
        denial_count = 0
        for i, grant in enumerate(grants):
            for j, conversation in enumerate(conversations):
                if i != j:
                    require(
                        h.request("/conversations/" + conversation, grant["token"])[0] == 404,
                        "Private conversation crossed identities",
                    )
                    denial_count += 1
        applicant = next(g for g in grants if g.get("collaboration_role") == "applicant")
        manager = next(g for g in grants if g.get("collaboration_role") == "safety_manager")
        task = conn.execute(
            "SELECT task_id FROM anlan_v2.collaboration_applications WHERE tenant_id=%s "
            "AND applicant_user_id=%s AND reviewer_user_id=%s ORDER BY updated_at DESC LIMIT 1",
            (
                applicant["identity"]["tenant_id"],
                applicant["identity"]["user_id"],
                manager["identity"]["user_id"],
            ),
        ).fetchone()
        require(task is not None, "Shared task history missing")
        for grant in (applicant, manager):
            require(
                h.request("/collaboration/applications/" + task[0], grant["token"])[0] == 200,
                "Shared task read failed",
            )
        require(
            h.request("/tasks/" + task[0] + "/history", manager["token"])[0] == 404,
            "Reviewer gained private task history",
        )
    return dict(
        saved_query_types=sorted(query_types),
        private_threads=len(conversations),
        cross_role_denials=denial_count,
        existing_shared_task_reads=2,
        owner_only_history_status=404,
        zero_write=True,
    )


def verify_active(h):
    config = json.loads(CONFIG.read_text())
    infos = h.wait_ready(config)
    require(h.request("/healthz")[0] == 200, "Health failed")
    require(h.request("/console/api/info")[0] == 401, "Anonymous boundary failed")
    for grant in config["tokens"]:
        require(h.request("/readyz", grant["token"])[0] == 200, "Authenticated readiness failed")
    manifest = json.loads((NEW / "rollout.json").read_text())
    require(migration_versions(h) == manifest["migrations_before"], "Migration set changed")
    verify_dependencies(h, NEW)
    probe = import_probe(h, NEW)
    query = read_only_query_probe(h, config)
    public = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in ("/anlan/healthz", "/anlan/console"):
        with opener.open("http://47.93.218.52" + path, timeout=10) as response:
            require(response.status == 200, "Public health failed")
            public[path] = response.status
    return dict(
        migrations=manifest["migrations_before"],
        import_probe=probe,
        roles=[
            dict(role=g.get("collaboration_role") or "legacy", model_mode=i["model_mode"])
            for g, i in zip(config["tokens"], infos, strict=True)
        ],
        public_status=public,
        query_acceptance=query,
        zero_write_probe=True,
        mcp_registered_or_enabled=False,
        mcp_schema_migrations_applied=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate", "forward", "rollback"])
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--source-commit")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            require(
                args.wheel is not None and args.source_commit is not None,
                "Wheel and source commit required",
            )
            result = prepare(args.wheel, args.source_commit)
        elif args.action == "rollback":
            result = rollback()
        else:
            result = activate(forward=args.action == "forward")
    except Exception as exc:
        print(
            json.dumps(
                dict(
                    status="failed",
                    error_type=type(exc).__name__,
                    details=str(exc)
                    if isinstance(exc, RuntimeError) and str(exc).startswith("Activation failed;")
                    else "Private output hidden",
                )
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
