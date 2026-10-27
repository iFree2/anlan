"""Persistent, idempotent preflight jobs use the actual local PostgreSQL fixture."""

import pytest
from test_events_postgres import dsn, run  # noqa: F401
from test_preflight_bindings import setup
from test_preflight_contracts import command

from anlan.common.errors import InvalidTransition
from anlan.preflight.contracts import EvidenceKey

pytestmark = pytest.mark.postgres


def test_same_evidence_key_creates_one_job_and_preserves_result_history(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            store = service.store
            await store.initialize()
            await service.confirm(actors[0], state["task_id"], command())
            key = EvidenceKey(
                task_id=state["task_id"],
                material_revision=1,
                binding_revision=1,
                application_version=1,
            )
            first = await store.enqueue(actors[0], key, {"fields": {"work_method": "焊接"}})
            again = await store.enqueue(actors[0], key, {"fields": {"work_method": "焊接"}})
            assert again["job_id"] == first["job_id"]
            attempt = await store.claim(first["job_id"])
            assert attempt is not None
            result = await store.finish(
                first["job_id"],
                attempt["attempt_id"],
                {"ready": False, "issues": ["knowledge_citations_missing"], "citation_ids": []},
            )
            assert result["check_id"]
            assert (
                await store.finish(
                    first["job_id"],
                    attempt["attempt_id"],
                    {"ready": True, "issues": [], "citation_ids": ["forged"]},
                )
                == result
            )

    run(scenario())


def test_expired_lease_creates_audited_attempt_and_fences_late_writer(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            await service.confirm(actors[0], state["task_id"], command())
            key = EvidenceKey(
                task_id=state["task_id"],
                material_revision=1,
                binding_revision=1,
                application_version=1,
            )
            job = await service.store.enqueue(actors[0], key, {"fields": {}})
            first = await service.store.claim(job["job_id"])
            assert await service.store.claim(job["job_id"]) is None
            async with service.store.connection() as conn:
                await conn.execute(
                    "UPDATE anlan_v2.precheck_jobs SET lease_until="
                    "clock_timestamp()-interval '1 second' WHERE job_id=%s",
                    (job["job_id"],),
                )
            second = await service.store.claim(job["job_id"])
            assert second["attempt_id"] != first["attempt_id"]
            with pytest.raises(InvalidTransition):
                await service.store.finish(job["job_id"], first["attempt_id"], {"ready": True})
            await service.store.finish(job["job_id"], second["attempt_id"], {"ready": False})
            async with service.store.connection() as conn:
                rows = await (
                    await conn.execute(
                        "SELECT status FROM anlan_v2.precheck_attempts "
                        "WHERE job_id=%s ORDER BY started_at",
                        (job["job_id"],),
                    )
                ).fetchall()
                assert [r["status"] for r in rows] == ["expired", "completed"]

    run(scenario())


def test_database_protects_results_and_input_snapshot_from_mutation(dsn, tmp_path):  # noqa: F811
    from psycopg.errors import RaiseException

    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            await service.confirm(actors[0], state["task_id"], command())
            key = EvidenceKey(
                task_id=state["task_id"],
                material_revision=1,
                binding_revision=1,
                application_version=1,
            )
            job = await service.store.enqueue(actors[0], key, {"fields": {}})
            attempt = await service.store.claim(job["job_id"])
            await service.store.finish(job["job_id"], attempt["attempt_id"], {"ready": False})
            for sql in (
                "UPDATE anlan_v2.precheck_results SET result='{}' WHERE job_id=%s",
                "DELETE FROM anlan_v2.precheck_results WHERE job_id=%s",
                "UPDATE anlan_v2.precheck_jobs SET input_snapshot='{}' WHERE job_id=%s",
            ):
                async with service.store.connection() as conn:
                    with pytest.raises(RaiseException):
                        await conn.execute(sql, (job["job_id"],))

    run(scenario())


@pytest.mark.parametrize("interrupted", [False, True], ids=["queued", "running"])
def test_real_new_process_recovers_persisted_readonly_job(dsn, tmp_path, interrupted):  # noqa: F811
    import json
    import os
    import subprocess
    import sys

    from test_preflight_service import integrated

    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, bindings, actors, state, collab, _):
            submitted = await collab.execute(
                actors[0],
                state["task_id"],
                "submit",
                dict(
                    request_id="submit",
                    expected_application_version=1,
                    expected_material_revision=1,
                    expected_binding_revision=1,
                    reviewer_user_id=actors[1].user_id,
                ),
            )
            config = bindings.config.model_dump(mode="json")
            config["tokens"] = [
                g.model_dump(mode="json") | {"token": g.token.get_secret_value()}
                for g in bindings.config.tokens
            ]
            environment = {
                **os.environ,
                "ANLAN_TEST_DATABASE_URL": dsn,
                "B2_CONFIG": json.dumps(config),
                "B2_JOB": submitted["precheck_job_id"],
                "B2_MODE": "claim" if interrupted else "run",
                "PYTHONUTF8": "1",
            }
            script = """
import asyncio, os
from anlan.interfaces.service_config import ServiceConfig
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.knowledge.store import KnowledgeStore
from anlan.preflight.service import PreflightService
from anlan.preflight.runner import PreflightRunner
from anlan.tools.queries import FactTools
class Embeddings:
    model_id='unit-double-512'
    async def embed(self,texts): return [[1.0]+[0.0]*511 for _ in texts]
async def main():
    config=ServiceConfig.model_validate_json(os.environ['B2_CONFIG'])
    dsn=os.environ['ANLAN_TEST_DATABASE_URL']
    clock=lambda: config.as_of
    knowledge=KnowledgeStore(dsn,Embeddings(),clock=clock)
    service=PreflightService(dsn,config,
        lambda: postgres_service(dsn,OfflineAnalyzer(),access_config=config),
        PreflightRunner(FactTools(config.facts_dir,clock=clock),knowledge,clock=clock))
    if os.environ['B2_MODE']=='claim':
        assert await service.store.claim(os.environ['B2_JOB'])
        os._exit(47)
    result=await service.process_next(os.environ['B2_JOB'])
    assert result['result']['ready']
asyncio.run(main(),loop_factory=asyncio.SelectorEventLoop)
"""
            first = subprocess.run(
                [sys.executable, "-c", script], env=environment, capture_output=True, timeout=30
            )
            assert first.returncode == (47 if interrupted else 0), first.stderr.decode()
            if interrupted:
                async with bindings.store.connection() as conn:
                    await conn.execute(
                        "UPDATE anlan_v2.precheck_jobs SET lease_until="
                        "clock_timestamp()-interval '1 second' WHERE job_id=%s",
                        (submitted["precheck_job_id"],),
                    )
                second = subprocess.run(
                    [sys.executable, "-c", script],
                    env=environment | {"B2_MODE": "run"},
                    capture_output=True,
                    timeout=30,
                )
                assert second.returncode == 0, second.stderr.decode()
            latest = await preflight.store.latest(actors[0].tenant_id, state["task_id"])
            assert latest["result"]["ready"]
            async with bindings.store.connection() as conn:
                attempts = await (
                    await conn.execute(
                        "SELECT status FROM anlan_v2.precheck_attempts "
                        "WHERE job_id=%s ORDER BY started_at",
                        (latest["job_id"],),
                    )
                ).fetchall()
                assert [a["status"] for a in attempts] == (
                    ["expired", "completed"] if interrupted else ["completed"]
                )

    run(scenario())
