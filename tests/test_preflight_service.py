import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from test_events_postgres import dsn, run  # noqa: F401
from test_knowledge import DOCUMENT, UnitEmbeddings
from test_preflight_bindings import setup
from test_preflight_catalog import metadata
from test_preflight_contracts import command as binding_command

from anlan.common.models import Identity
from anlan.knowledge.store import KnowledgeStore
from anlan.preflight.runner import PreflightRunner
from anlan.preflight.service import PreflightService
from anlan.tools.queries import FactTools

NOW = datetime(2026, 10, 27, tzinfo=UTC)


async def populate_sources(dsn, config, actors, directory):  # noqa: F811
    config.facts_dir = directory
    config.as_of = NOW
    from anlan.preflight.contracts import PrecheckCatalog

    config.precheck_catalogs = [PrecheckCatalog.model_validate(metadata(actors[0].tenant_id))]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "access.json").write_text(
        json.dumps(
            {
                "data_origin": "SYNTHETIC",
                "version": "v1",
                "records": [
                    dict(
                        tenant_id=actor.tenant_id,
                        user_id=actor.user_id,
                        worker_ids=["worker-a", "worker-b"],
                        area_ids=["area-a", "area-b"],
                    )
                    for actor in actors
                    if actor.tenant_id == actors[0].tenant_id
                ],
            }
        ),
        encoding="utf-8",
    )
    for filename, prefix, status in [
        ("qualifications.json", "worker", "active"),
        ("areas.json", "area", "normal"),
    ]:
        records = [
            dict(
                tenant_id=actors[0].tenant_id,
                record_id=prefix + "-" + letter,
                object_id=prefix + "-" + letter,
                observed_at="2026-01-01T00:00:00Z",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                status=status,
                **({"qualification_type": "welding"} if prefix == "worker" else {}),
            )
            for letter in ("a", "b")
        ]
        (directory / filename).write_text(
            json.dumps(dict(data_origin="SYNTHETIC", version="v1", records=records)),
            encoding="utf-8",
        )
    knowledge = KnowledgeStore(dsn, UnitEmbeddings(), clock=lambda: NOW)
    await knowledge.initialize()
    await knowledge.ingest(actors[0], DOCUMENT | {"allowed_users": [a.user_id for a in actors]})
    return knowledge


@asynccontextmanager
async def integrated(dsn, directory):  # noqa: F811
    async with setup(dsn, directory) as (bindings, actors, state, collab):
        knowledge = await populate_sources(dsn, bindings.config, actors, directory)
        preflight = PreflightService(
            dsn,
            bindings.config,
            bindings.service_context_factory,
            PreflightRunner(FactTools(directory, clock=lambda: NOW), knowledge, clock=lambda: NOW),
        )
        await bindings.confirm(actors[0], state["task_id"], binding_command())
        yield preflight, bindings, actors, state, collab, knowledge


@pytest.mark.asyncio
async def test_runner_uses_bound_ids_and_material_method_instead_of_fixed_alert_question():
    calls = []

    class Facts:
        async def query_worker_qualification(self, actor, value):
            calls.append(value)
            return {
                "tool": "query_worker_qualification",
                "outcome": "ok",
                "facts": {"status": "active"},
                "source": {"valid_until": "2030-01-01T00:00:00+00:00"},
            }

        async def query_area_status(self, actor, value):
            calls.append(value)
            return {
                "tool": "query_area_status",
                "outcome": "ok",
                "facts": {"status": "normal"},
                "source": {"valid_until": "2030-01-01T00:00:00+00:00"},
            }

    class Knowledge:
        async def search(self, actor, value):
            calls.append(value)
            return {
                "outcome": "ok",
                "reason": None,
                "queried_at": NOW.isoformat(),
                "citations": [
                    {
                        "chunk_id": "c",
                        "doc_id": "d",
                        "version": 1,
                        "source": "synthetic",
                        "content_hash": "x",
                        "document_hash": "y",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "valid_until": "2030-01-01T00:00:00+00:00",
                    }
                ],
            }

    result = await PreflightRunner(Facts(), Knowledge()).run(
        Identity(tenant_id="t", user_id="u"),
        {"worker_id": "worker-a", "qualification_type": "welding", "area_id": "area-a"},
        {"work_method": "焊接", "work_object": "管道"},
    )
    assert calls[0] == {"worker_id": "worker-a", "qualification_type": "welding"}
    assert calls[1] == {"area_id": "area-a"}
    assert "焊接" in calls[2]["question"] and "管道" in calls[2]["question"]
    assert result["ready"]


@pytest.mark.postgres
def test_real_fact_and_knowledge_queries_persist_without_model(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, _, actors, state, collab, _):
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
            result = await preflight.process_next(submitted["precheck_job_id"])
            assert result["result"]["ready"] and not result["result"].get("stale")
            assert "work_method" not in result["result"]["question"]
            shared = await collab.get(actors[1], state["task_id"])
            assert shared["precheck"]["current"]
            check = shared["precheck"]
            complete = await collab.execute(
                actors[1],
                state["task_id"],
                "complete_review",
                dict(
                    request_id="complete",
                    expected_application_version=2,
                    expected_material_revision=1,
                    expected_binding_revision=1,
                    expected_check_id=check["check_id"],
                    applied_knowledge_citation_ids=check["evidence"]["citation_ids"],
                    conclusion="人工核对",
                ),
            )
            assert complete["application"]["status"] == "review_completed"

    run(scenario())


@pytest.mark.postgres
@pytest.mark.parametrize(
    "change",
    [
        "qualification",
        "area",
        "withdraw",
        "knowledge_version",
        "knowledge_acl",
        "actor_acl",
        "time",
        "binding",
        "material",
    ],
)
def test_source_and_input_changes_block_frozen_completion(dsn, tmp_path, change):  # noqa: F811
    from datetime import timedelta

    from anlan.common.errors import AccessDenied, InvalidTransition

    async def scenario():
        async with integrated(dsn, tmp_path) as (
            preflight,
            bindings,
            actors,
            state,
            collab,
            knowledge,
        ):
            task = state["task_id"]
            submitted = await collab.execute(
                actors[0],
                task,
                "submit",
                dict(
                    request_id="submit",
                    expected_application_version=1,
                    expected_material_revision=1,
                    expected_binding_revision=1,
                    reviewer_user_id=actors[1].user_id,
                ),
            )
            result = await preflight.process_next(submitted["precheck_job_id"])
            body = dict(
                request_id="complete",
                expected_application_version=2,
                expected_material_revision=1,
                expected_binding_revision=1,
                expected_check_id=result["check_id"],
                applied_knowledge_citation_ids=result["result"]["citation_ids"],
                conclusion="人工核对",
            )
            if change in {"qualification", "area"}:
                path = tmp_path / (
                    "qualifications.json" if change == "qualification" else "areas.json"
                )
                data = json.loads(path.read_text(encoding="utf-8"))
                data["version"] = "v2"
                path.write_text(json.dumps(data), encoding="utf-8")
            elif change == "withdraw":
                await knowledge.withdraw(actors[0], DOCUMENT["doc_id"])
            elif change == "knowledge_version":
                await knowledge.ingest(
                    actors[0],
                    DOCUMENT | {"version": 2, "allowed_users": [a.user_id for a in actors]},
                )
            elif change == "knowledge_acl":
                async with bindings.store.connection() as conn:
                    await conn.execute(
                        "UPDATE anlan_v2.knowledge_documents SET allowed_users=%s "
                        "WHERE tenant_id=%s",
                        ([actors[0].user_id], actors[0].tenant_id),
                    )
            elif change == "actor_acl":
                data = json.loads((tmp_path / "access.json").read_text(encoding="utf-8"))
                data["records"] = [r for r in data["records"] if r["user_id"] != actors[1].user_id]
                (tmp_path / "access.json").write_text(json.dumps(data), encoding="utf-8")
            elif change == "time":
                collab.preflight.clock = lambda: NOW + timedelta(minutes=11)
            else:
                await collab.execute(
                    actors[1],
                    task,
                    "request_changes",
                    dict(
                        request_id="return",
                        expected_application_version=2,
                        expected_material_revision=1,
                        questions=["补充"],
                    ),
                )
                if change == "binding":
                    await bindings.confirm(
                        actors[0],
                        task,
                        binding_command(
                            request_id="change-binding",
                            expected_binding_revision=1,
                            worker_id="worker-b",
                        ),
                    )
                else:
                    from test_material_revisions import PATCH

                    async with bindings.service_context_factory() as workflow:
                        await workflow.revise(actors[0], task, 1, PATCH)
            with pytest.raises((InvalidTransition, AccessDenied)):
                await collab.execute(actors[1], task, "complete_review", body)

    run(scenario())


@pytest.mark.postgres
def test_io_releases_task_lock_and_old_round_cannot_publish_as_current(dsn, tmp_path):  # noqa: F811
    import asyncio

    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, _, actors, state, collab, _):
            task = state["task_id"]
            submitted = await collab.execute(
                actors[0],
                task,
                "submit",
                dict(
                    request_id="submit",
                    expected_application_version=1,
                    expected_material_revision=1,
                    expected_binding_revision=1,
                    reviewer_user_id=actors[1].user_id,
                ),
            )
            entered, release = asyncio.Event(), asyncio.Event()
            runner = preflight.runner

            class PausedRunner:
                async def run(self, *args):
                    entered.set()
                    await release.wait()
                    return await runner.run(*args)

            preflight.runner = PausedRunner()
            pending = asyncio.create_task(preflight.process_next(submitted["precheck_job_id"]))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                # This uses a separate real PG registry connection while I/O is paused.
                assert (await collab.get(actors[1], task))["application"].status == "under_review"
                recheck = await preflight.recheck(
                    actors[1],
                    task,
                    dict(
                        request_id="new-round",
                        expected_application_version=2,
                        expected_material_revision=1,
                        expected_binding_revision=1,
                        reason="显式重查",
                    ),
                )
            finally:
                release.set()
            old = await pending
            assert old["result"]["stale"] is True
            latest = await preflight.store.latest(actors[0].tenant_id, task)
            assert latest["job_id"] == recheck["job_id"] and latest["result"] is None

    run(scenario())


@pytest.mark.postgres
def test_busy_registry_relinquishes_lease_for_readonly_retry(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, bindings, actors, state, collab, _):
            submit = await collab.execute(
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
            async with bindings.service_context_factory() as workflow:
                async with workflow._registry.locked(actors[0], state["task_id"]):
                    assert await preflight.process_next(submit["precheck_job_id"]) is None
            assert await preflight.store.claim(submit["precheck_job_id"]) is not None

    run(scenario())


@pytest.mark.postgres
def test_completion_holds_actual_source_row_lock_until_commit(dsn, tmp_path, monkeypatch):  # noqa: F811
    import asyncio

    async def scenario():
        async with integrated(dsn, tmp_path) as (
            preflight,
            bindings,
            actors,
            state,
            collab,
            knowledge,
        ):
            task = state["task_id"]
            submit = await collab.execute(
                actors[0],
                task,
                "submit",
                dict(
                    request_id="submit",
                    expected_application_version=1,
                    expected_material_revision=1,
                    expected_binding_revision=1,
                    reviewer_user_id=actors[1].user_id,
                ),
            )
            evidence = await preflight.process_next(submit["precheck_job_id"])
            paused, release, connected = asyncio.Event(), asyncio.Event(), asyncio.Event()
            original = collab.store.save_receipt
            original_connect = knowledge._connect
            source_pid = None

            async def pause(*args, **kwargs):
                paused.set()
                await release.wait()
                return await original(*args, **kwargs)

            async def observe_connection():
                nonlocal source_pid
                conn = await original_connect()
                source_pid = conn.info.backend_pid
                connected.set()
                return conn

            with monkeypatch.context() as context:
                context.setattr(collab.store, "save_receipt", pause)
                context.setattr(knowledge, "_connect", observe_connection)
                completion = asyncio.create_task(
                    collab.execute(
                        actors[1],
                        task,
                        "complete_review",
                        dict(
                            request_id="complete",
                            expected_application_version=2,
                            expected_material_revision=1,
                            expected_binding_revision=1,
                            expected_check_id=evidence["check_id"],
                            conclusion="人工核对",
                            applied_knowledge_citation_ids=evidence["result"]["citation_ids"],
                        ),
                    )
                )
                withdraw = None
                try:
                    await asyncio.wait_for(paused.wait(), 5)
                    withdraw = asyncio.create_task(
                        knowledge.withdraw(actors[0], DOCUMENT["doc_id"])
                    )
                    await asyncio.wait_for(connected.wait(), 5)
                    async with asyncio.timeout(5), bindings.store.connection() as conn:
                        while not withdraw.done():
                            waiting = await (
                                await conn.execute(
                                    "SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted",
                                    (source_pid,),
                                )
                            ).fetchone()
                            if waiting:
                                break
                        assert not withdraw.done(), (
                            "source update bypassed completion metadata locks"
                        )
                finally:
                    release.set()
                    await completion
                    if withdraw:
                        await withdraw
            historical = await collab.get(actors[1], task)
            assert historical["application"].status == "review_completed"
            assert historical["precheck"]["current"] is False

    run(scenario())
