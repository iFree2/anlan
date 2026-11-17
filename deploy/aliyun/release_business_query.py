"""Fixed-target SQL021 release; preserve private config, history and paid-model ledger."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from collections import Counter
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from uuid import uuid4

ROOT = Path("/opt/anlan2")
BASE = ROOT / "releases/p13-preflight-20261101b"
NEW = ROOT / "releases/business-query-20261117"
MAINTENANCE = ROOT / "releases/p12-maintenance-20261025"
SHARED = ROOT / "shared"
CONFIG = SHARED / "console.json"
ENV = SHARED / "app.env"
BACKUP = SHARED / "before-business-query-20261117"
WHEEL_SHA = "fd2c20866774f2c03a3e3ce6a5e3cd9ea79fc29c3c04b03c5ad1ef67c9b975e0"
CONFIG_SHA = "7b03174b784e69e85d10f057df46c690bab077ebdbfedcb88d0e0d8d7ec0deaf"
WHEEL_NAME = "anlan-0.1.0-py3-none-any.whl"
REQUIRED = {
    "anlan/business_query/contracts.py",
    "anlan/business_query/service.py",
    "anlan/infrastructure/business_queries.py",
    "anlan/sql/021_business_queries.sql",
}
APPEND_TABLES = {
    "conversations",
    "conversation_messages",
    "conversation_routes",
    "business_query_receipts",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def harness():
    spec = importlib.util.spec_from_file_location(
        "query_release_harness", ROOT / "release-collaboration-20261025.py"
    )
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    h.NEW = NEW
    return h


def validate_wheel(path, expected_sha):
    path = Path(path)
    require(digest(path.read_bytes()) == expected_sha, "Wheel SHA-256 mismatch")
    with zipfile.ZipFile(path) as archive:
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
        require(REQUIRED <= set(archive.namelist()), "Missing query resources or SQL021")
    return expected_sha


def dependency_signature(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        require(len(names) == 1, "Wheel metadata missing")
        metadata = BytesParser().parsebytes(archive.read(names[0]))
        return sorted(metadata.get_all("Requires-Dist", [])), metadata["Requires-Python"]


def systemd_metadata(h):
    document = {
        "unit": h.command("systemctl", "cat", "anlan2-console"),
        "properties": h.command(
            "systemctl",
            "show",
            "anlan2-console",
            "--property=FragmentPath,DropInPaths,User,Group,WorkingDirectory",
        ),
    }
    return digest(json.dumps(document, sort_keys=True).encode()), document


def write_report(path, document):
    h = harness()
    temporary = path.with_name(path.name + ".pending-" + uuid4().hex)
    h.private_json(temporary, document)
    os.replace(temporary, path)


def migration_versions(h):
    import psycopg

    with psycopg.connect(h.environment()["ANLAN_DATABASE_URL"]) as conn:
        return sorted(
            r[0] for r in conn.execute("SELECT version FROM anlan_v2.anlan_schema_migrations")
        )


def preserved(before, after):
    return all(
        not (Counter(rows) - Counter(after["rows"].get(table, [])))
        for table, rows in before["rows"].items()
    )


def assert_preserved(before, after):
    require(preserved(before, after), "Existing rows changed or disappeared")
    require(before["ledger"] == after["ledger"], "Unexpected paid model request")
    for table, rows in before["rows"].items():
        if table not in APPEND_TABLES:
            require(rows == after["rows"].get(table), "Business state changed during release")


def prepare(wheel, expected_sha=WHEEL_SHA):
    h = harness()
    require(os.geteuid() == 0, "Scoped root deployment required")
    require((ROOT / "current").resolve() == BASE, "Unexpected active release")
    require(not NEW.exists() and not BACKUP.exists(), "Release already prepared; inspect it")
    require(MAINTENANCE.is_dir(), "Maintenance application missing")
    require(digest(CONFIG.read_bytes()) == CONFIG_SHA, "Unexpected trusted configuration")
    wheel = Path(wheel)
    validate_wheel(wheel, expected_sha)
    require(
        dependency_signature(wheel) == dependency_signature(BASE / WHEEL_NAME),
        "Dependencies differ from the active release",
    )
    before = h.snapshot()
    h.require_quiescent(before["pending"])
    h.wait_ready(json.loads(CONFIG.read_text()))
    versions = migration_versions(h)
    require(21 not in versions and {17, 18, 19, 20} <= set(versions), "Unexpected migration state")
    unit_sha, unit_document = systemd_metadata(h)
    BACKUP.mkdir(mode=0o700)
    for name in ("console.json", "app.env"):
        shutil.copy2(SHARED / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    h.private_json(BACKUP / "systemd.json", unit_document)
    h.private_json(BACKUP / "before.json", before)
    h.private_json(
        BACKUP / "recovery.json",
        {
            "base": str(BASE),
            "forward": str(NEW),
            "maintenance": str(MAINTENANCE),
            "policy": (
                "Never restore a database, erase audit rows, or restart the legacy write release."
            ),
        },
    )
    spec = importlib.util.spec_from_file_location(
        "query_backup", ROOT / "release-preflight-20261101.py"
    )
    p13 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p13)
    dump_sha = p13._backup_database(h, BACKUP)
    require(h.snapshot()["rows"] == before["rows"], "Data changed while backing up")
    NEW.mkdir(mode=0o755)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(NEW / "app")
    shutil.copy2(wheel, NEW / WHEEL_NAME)
    for name in ("venv", "examples"):
        (NEW / name).symlink_to((BASE / name).resolve(), target_is_directory=True)
    h.command(
        str(NEW / "venv/bin/python"),
        "-c",
        "from anlan.interfaces.api import create_app;"
        "from anlan.interfaces.service_config import ServiceConfig;"
        "ServiceConfig.from_file(" + repr(str(CONFIG)) + ")",
        env=h.environment() | {"PYTHONPATH": str(NEW / "app")},
    )
    report = {
        "status": "prepared",
        "base": str(BASE),
        "new_release": str(NEW),
        "wheel_sha256": expected_sha,
        "database_dump_sha256": dump_sha,
        "config_sha256": digest(CONFIG.read_bytes()),
        "env_sha256": digest(ENV.read_bytes()),
        "systemd_sha256": unit_sha,
        "migrations_before": versions,
        "before_counts": before["counts"],
        "ledger_before": before["ledger"],
        "new_model_requests": 0,
    }
    write_report(NEW / "rollout.json", report)
    return report


def migrate(h):
    import psycopg

    with psycopg.connect(h.environment()["ANLAN_DATABASE_URL"]) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(73421121)")
        conn.execute((NEW / "app/anlan/sql/021_business_queries.sql").read_text(), prepare=False)


def activation_gate(h, *, forward=False):
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
    require(systemd_metadata(h)[0] == manifest["systemd_sha256"], "Systemd configuration changed")
    require(
        digest((BACKUP / "database.dump").read_bytes()) == manifest["database_dump_sha256"],
        "Backup fingerprint changed",
    )
    validate_wheel(NEW / WHEEL_NAME, manifest["wheel_sha256"])
    before = json.loads((BACKUP / "before.json").read_text())
    current = h.snapshot()
    h.require_quiescent(current["pending"])
    if forward:
        assert_preserved(before, current)
    else:
        require(before["rows"] == current["rows"], "Data changed after backup")
    return manifest, before


def activate(*, forward=False):
    h = harness()
    manifest, before = activation_gate(h, forward=forward)
    try:
        h.command("systemctl", "stop", "anlan2-console")
        stopped = h.snapshot()
        h.require_quiescent(stopped["pending"])
        if forward:
            assert_preserved(before, stopped)
        else:
            require(before["rows"] == stopped["rows"], "Data changed during stop")
        migrate(h)
        h.switch_release(NEW)
        h.command("systemctl", "start", "anlan2-console")
        verification = verify_active(h)
        after = h.snapshot()
        assert_preserved(before, after)
        require(
            digest(CONFIG.read_bytes()) == manifest["config_sha256"]
            and digest(ENV.read_bytes()) == manifest["env_sha256"],
            "Configuration changed",
        )
        require(
            systemd_metadata(h)[0] == manifest["systemd_sha256"], "Systemd configuration changed"
        )
        report = {
            **manifest,
            **verification,
            "status": "activated",
            "current": str(NEW),
            "service_pid": h.command(
                "systemctl", "show", "-p", "MainPID", "--value", "anlan2-console"
            ),
            "old_rows_preserved": True,
            "business_state_unchanged": True,
            "ledger_after": after["ledger"],
            "ledger_unchanged": True,
            "after_counts": after["counts"],
            "new_model_requests": 0,
            "natural_language_live_classifier_tested": False,
        }
        write_report(NEW / "rollout.json", report)
        return report
    except Exception:
        h.rollback()
        raise RuntimeError(
            "Activation failed; maintenance remains active; private output hidden"
        ) from None


def verify_active(h):
    config = json.loads(CONFIG.read_text())
    infos = h.wait_ready(config)
    require(h.request("/console/api/info")[0] == 401, "Anonymous authentication boundary failed")
    require(h.request("/healthz")[0] == 200, "Local health check failed")
    for grant in config["tokens"]:
        require(h.request("/readyz", grant["token"])[0] == 200, "Authenticated readiness failed")
    manifest = json.loads((NEW / "rollout.json").read_text())
    versions = migration_versions(h)
    require(
        set(versions) == set(manifest["migrations_before"]) | {21}, "Unexpected migration changes"
    )
    sys.path.insert(0, str(NEW / "app"))
    result = asyncio.run(query_probe(h, config))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    public = {}
    for path in ("/anlan/healthz", "/anlan/console"):
        with opener.open("http://47.93.218.52" + path, timeout=10) as response:
            require(response.status == 200, "Public health check failed")
            public[path] = response.status
    return {
        "roles": [
            {"role": grant.get("collaboration_role", "legacy"), "model_mode": info["model_mode"]}
            for grant, info in zip(config["tokens"], infos, strict=True)
        ],
        "anonymous_status": 401,
        "migrations": versions,
        "public_status": public,
        "query_acceptance": result,
    }


async def query_probe(h, config):
    """Use a trusted proposal, real authorization/store/audit and actual HTTP readback."""
    import psycopg

    from anlan.business_query.service import BusinessQueryService
    from anlan.collaboration.service import CollaborationService
    from anlan.conversation.contracts import IntentProposal
    from anlan.conversation.service import ConversationService
    from anlan.infrastructure.business_queries import BusinessQueryAuditStore
    from anlan.infrastructure.conversations import ConversationStore
    from anlan.interfaces.collaboration_conversation import CollaborationConversationAdapter
    from anlan.interfaces.conversation_runtime import WorkflowAdapter
    from anlan.interfaces.service_config import ServiceConfig
    from anlan.interfaces.service_models import ServiceModels
    from anlan.knowledge.embeddings import LocalEmbeddings
    from anlan.knowledge.store import KnowledgeStore
    from anlan.llm.perception import ScriptedPerceptionModel

    cfg = ServiceConfig.from_file(CONFIG)
    dsn = h.environment()["ANLAN_DATABASE_URL"]
    # ServiceModels reads the existing live credentials. Query overrides skip classification;
    # no fake success, model-mode change or budget reservation is used.
    os.environ.update(h.environment())
    models = ServiceModels(dsn, cfg, ScriptedPerceptionModel)
    clock = lambda: cfg.as_of  # noqa: E731 -- retained fixed replay clock
    knowledge = KnowledgeStore(dsn, await LocalEmbeddings.create(cfg.embeddings_cache), clock=clock)
    workflow = CollaborationConversationAdapter(
        CollaborationService(dsn, cfg, models.material_service),
        WorkflowAdapter(models.material_service),
    )
    audit = BusinessQueryAuditStore(dsn)
    service = ConversationService(
        ConversationStore(dsn),
        models.conversation,
        workflow,
        BusinessQueryService(
            workflow, clock=clock, knowledge_provider=lambda: knowledge, audit=audit
        ),
    )
    grants = {g.collaboration_role or "legacy": g for g in cfg.tokens}
    applicant, manager = grants["applicant"], grants["safety_manager"]
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT task_id FROM anlan_v2.collaboration_applications WHERE tenant_id=%s "
            "AND applicant_user_id=%s AND reviewer_user_id=%s AND status<>'draft' "
            "ORDER BY updated_at DESC LIMIT 1",
            (applicant.identity.tenant_id, applicant.identity.user_id, manager.identity.user_id),
        ).fetchone()
        require(row is not None, "No existing assigned application for read-only acceptance")
        task = row[0]
        legacy = grants["legacy"].identity
        legacy_task = conn.execute(
            "SELECT task_id FROM anlan_v2.anlan_tasks WHERE tenant_id=%s AND user_id=%s "
            "ORDER BY created_at DESC LIMIT 1",
            (legacy.tenant_id, legacy.user_id),
        ).fetchone()
    require(legacy_task is not None, "Legacy owned task missing")
    probe_id = "business-query-20261117-" + uuid4().hex[:12]
    conversations, checks = {}, []
    async with models.lifespan():
        for role, grant in grants.items():
            marker = probe_id + "-PRIVATE-" + role
            conv = await service.create(grant.identity, request_id=probe_id + ":" + role)
            queries = [("safety_knowledge", "动火作业前有哪些依据需要核对？")]
            if role != "legacy":
                queries = [
                    ("application_status", "当前材料状态是什么？"),
                    ("application_details", "作业对象是什么？"),
                    ("process_guidance", "下一步怎么办？"),
                    *queries,
                ]
            for query_type, question in queries:
                explicit = task if query_type != "safety_knowledge" else None
                text = f"{marker} {question}" + (f" 申请 {task}" if explicit else "")
                result = await service.message(
                    grant.identity,
                    conv["conversation_id"],
                    request_id=probe_id + ":" + query_type,
                    expected_revision=conv["revision"],
                    text=text,
                    proposal_override=IntentProposal(
                        intent="query_" + query_type,
                        target_task_id=explicit,
                        user_explanation="受控发布验收只读提案",
                        classifier_version="ecs-query-probe-v1",
                    ),
                )
                require(not result.get("error_category"), "Query acceptance returned a failure")
                require(
                    result["active_task_id"] is None and result["pending_intent"] is None,
                    "Query changed binding or created a pending write",
                )
                source = next(m for m in reversed(result["messages"]) if m["role"] == "user")
                receipt = await audit.get(grant.identity, source["message_id"])
                require(
                    receipt["query_type"] == query_type
                    and receipt["actor_role"] == grant.collaboration_role,
                    "Query audit role/type mismatch",
                )
                require(
                    receipt["outcome"] in ({"ok", "unknown"} if role == "legacy" else {"ok"}),
                    "Query evidence unavailable for acceptance",
                )
                require(
                    not {"question", "answer", "facts", "citations"} & receipt.keys(),
                    "Audit contains raw private content",
                )
                status, visible = h.request(
                    "/conversations/" + conv["conversation_id"], grant.token.get_secret_value()
                )
                require(
                    status == 200
                    and visible["messages"][-1]["text"] == result["messages"][-1]["text"],
                    "Real HTTP query readback failed",
                )
                checks.append(
                    {
                        "role": role,
                        "query_type": query_type,
                        "outcome": receipt["outcome"],
                        "task_id": receipt["task_id"],
                        "material_revision": receipt["material_revision"],
                        "application_version": receipt["application_version"],
                        "citation_count": len(receipt["citation_ids"]),
                        "http_readback": 200,
                    }
                )
                conv = result
            conversations[role] = {"id": conv["conversation_id"], "marker": marker}
        for role, grant in grants.items():
            token = grant.token.get_secret_value()
            status, own = h.request("/conversations/" + conversations[role]["id"], token)
            require(
                status == 200 and conversations[role]["marker"] in str(own), "Own thread missing"
            )
            for other, target in conversations.items():
                if role != other:
                    require(target["marker"] not in str(own), "Private question crossed roles")
                    require(
                        h.request("/conversations/" + target["id"], token)[0] == 404,
                        "Cross-role private thread was visible",
                    )
        for grant in (applicant, manager):
            require(
                h.request("/collaboration/applications/" + task, grant.token.get_secret_value())[0]
                == 200,
                "Assigned task read failed",
            )
        require(
            h.request(f"/tasks/{task}/history", manager.token.get_secret_value())[0] == 404,
            "Reviewer gained owner-only history",
        )
        require(
            h.request("/tasks/" + legacy_task[0], grants["legacy"].token.get_secret_value())[0]
            == 200,
            "Legacy owned task read failed",
        )
    return {
        "probe_id": probe_id,
        "queries": checks,
        "private_threads": 3,
        "cross_role_denials": 6,
        "owner_only_history_status": 404,
        "existing_task_reads": 3,
        "binding_unchanged": True,
        "proposal_override": True,
        "paid_live_classifier_tested": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate", "forward", "rollback"])
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            require(args.wheel is not None, "Wheel required")
            result = prepare(args.wheel)
        elif args.action == "rollback":
            result = harness().rollback()
        else:
            result = activate(forward=args.action == "forward")
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "details": "Private output hidden; inspect maintenance and protected logs",
                }
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
