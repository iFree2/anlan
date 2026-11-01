import pytest
from test_events_postgres import dsn, run  # noqa: F401
from test_preflight_bindings import send, setup
from test_preflight_contracts import command as binding_command

from anlan.common.errors import AccessDenied, InvalidTransition

pytestmark = pytest.mark.postgres


def test_complete_review_requires_current_check_and_real_citation_selection(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (bindings, actors, state, collab):
            owner, reviewer, task = actors[0], actors[1], state["task_id"]
            await bindings.confirm(owner, task, binding_command())
            await send(
                collab,
                owner,
                task,
                "submit",
                expected_binding_revision=1,
                reviewer_user_id=reviewer.user_id,
            )
            with pytest.raises(InvalidTransition):
                await send(collab, reviewer, task, "complete_review", 2, conclusion="人工核对")

    run(scenario())


@pytest.mark.parametrize("change", ["binding", "source"])
def test_resubmit_accepts_real_binding_or_source_change_without_material_edit(
    dsn,  # noqa: F811
    tmp_path,
    change,
):  # noqa: F811
    import json

    from test_preflight_service import integrated

    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, bindings, actors, state, collab, _):
            task = state["task_id"]
            first = await send(
                collab,
                actors[0],
                task,
                "submit",
                expected_binding_revision=1,
                reviewer_user_id=actors[1].user_id,
            )
            await preflight.process_next(first["precheck_job_id"])
            await send(collab, actors[1], task, "request_changes", 2, questions=["补充依据"])
            revision = 1
            if change == "binding":
                await bindings.confirm(
                    actors[0],
                    task,
                    binding_command(
                        request_id="second",
                        expected_binding_revision=1,
                        worker_id="worker-b",
                        area_id="area-b",
                    ),
                )
                revision = 2
            else:
                path = tmp_path / "qualifications.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                data["version"] = "v2"
                path.write_text(json.dumps(data), encoding="utf-8")
                request = dict(
                    request_id="refresh",
                    expected_material_revision=1,
                    expected_binding_revision=1,
                    expected_application_version=3,
                    reason="来源已修复",
                )
                refreshed = await preflight.recheck(actors[0], task, request)
                assert await preflight.recheck(actors[0], task, request) == refreshed
                with pytest.raises(InvalidTransition):
                    await preflight.recheck(actors[0], task, request | {"reason": "不同载荷"})
                with pytest.raises(InvalidTransition):
                    await preflight.recheck(
                        actors[0], task, request | {"reason": request["reason"] + " "}
                    )
                await preflight.process_next(refreshed["job_id"])
            resubmitted = await send(
                collab,
                actors[0],
                task,
                "resubmit",
                3,
                expected_binding_revision=revision,
                reply="已补充",
            )
            result = await preflight.process_next(resubmitted["precheck_job_id"])
            assert result["result"]["ready"]
            if change == "binding":
                assert result["result"]["worker"]["object_id"] == "worker-b"
                assert result["result"]["area"]["object_id"] == "area-b"
            assert resubmitted["application"]["submitted_material_revision"] == 1

    run(scenario())


@pytest.mark.parametrize("missing", ["binding", "check", "citations", "foreign", "duplicate"])
def test_completion_rejects_missing_frozen_fields_and_arbitrary_references(dsn, tmp_path, missing):  # noqa: F811
    from test_preflight_service import integrated

    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, _, actors, state, collab, _):
            task = state["task_id"]
            submit = await send(
                collab,
                actors[0],
                task,
                "submit",
                expected_binding_revision=1,
                reviewer_user_id=actors[1].user_id,
            )
            result = await preflight.process_next(submit["precheck_job_id"])
            body = dict(
                request_id="complete",
                expected_application_version=2,
                expected_material_revision=1,
                expected_binding_revision=1,
                expected_check_id=result["check_id"],
                applied_knowledge_citation_ids=result["result"]["citation_ids"],
                conclusion="已核对",
            )
            if missing == "binding":
                body.pop("expected_binding_revision")
            elif missing == "check":
                body.pop("expected_check_id")
            elif missing == "citations":
                body.pop("applied_knowledge_citation_ids")
            elif missing == "foreign":
                body["applied_knowledge_citation_ids"] = ["invented"]
            else:
                body["applied_knowledge_citation_ids"] *= 2
            with pytest.raises(InvalidTransition):
                await collab.execute(actors[1], task, "complete_review", body)

    run(scenario())


def test_gap_does_not_prevent_read_or_requesting_changes(dsn, tmp_path):  # noqa: F811
    import json

    from test_preflight_service import integrated

    async def scenario():
        async with integrated(dsn, tmp_path) as (preflight, _, actors, state, collab, _):
            path = tmp_path / "qualifications.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["records"][0]["status"] = "suspended"
            path.write_text(json.dumps(data), encoding="utf-8")
            task = state["task_id"]
            first = await send(
                collab,
                actors[0],
                task,
                "submit",
                expected_binding_revision=1,
                reviewer_user_id=actors[1].user_id,
            )
            result = await preflight.process_next(first["precheck_job_id"])
            assert not result["result"]["ready"]
            view = await collab.get(actors[1], task)
            assert view["precheck"]["status"] == "gap"
            assert view["application"].status == "under_review"
            await send(collab, actors[1], task, "request_changes", 2, questions=["请补资质"])

    run(scenario())


def test_http_and_frozen_adapter_cannot_upgrade_old_completion_payload(dsn):  # noqa: F811
    from test_collaboration_api import clients, command, completion, start
    from test_collaboration_api import send as http_send

    from anlan.collaboration.service import CollaborationService
    from anlan.conversation.contracts import FrozenCollaborationCommand
    from anlan.interfaces.collaboration_conversation import CollaborationConversationAdapter
    from anlan.interfaces.conversation_runtime import WorkflowAdapter

    async def scenario():
        async with clients(dsn) as (sessions, actors, config):
            task = (await start(sessions[0]))["task_id"]
            await http_send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            ready = await completion(sessions[1], task, command(2, conclusion="已核对"))
            old = command(2, conclusion="旧卡片")
            response = await sessions[1].post(
                f"/collaboration/applications/{task}/commands/complete_review", json=old
            )
            assert response.status_code == 409
            factory = sessions[0]._transport.app.state.preflight.service_context_factory
            adapter = CollaborationConversationAdapter(
                CollaborationService(dsn, config, factory), WorkflowAdapter(factory)
            )
            with pytest.raises(InvalidTransition):
                await adapter.execute(
                    actors[1],
                    FrozenCollaborationCommand(task_id=task, action="complete_review", payload=old),
                )
            for extra in ({"ready": True}, {"actor": actors[0].model_dump()}):
                response = await sessions[1].post(
                    f"/collaboration/applications/{task}/commands/complete_review",
                    json=ready | extra,
                )
                assert response.status_code == 422
            # Deliberately old composition is still forced through the same database policy.
            from anlan.interfaces.runtime import postgres_service
            from anlan.workflows.material_analysis import OfflineAnalyzer

            old_service = CollaborationService(
                dsn, config, lambda: postgres_service(dsn, OfflineAnalyzer())
            )
            with pytest.raises((InvalidTransition, AccessDenied)):
                await old_service.execute(actors[1], task, "complete_review", old)

    run(scenario())


def test_legacy_unbound_submission_requires_supplement_and_can_resubmit_same_material(
    dsn,  # noqa: F811
    tmp_path,
):
    from test_preflight_service import populate_sources

    from anlan.preflight.runner import PreflightRunner
    from anlan.preflight.service import PreflightService
    from anlan.tools.queries import FactTools

    async def scenario():
        async with setup(dsn, tmp_path) as (bindings, actors, state, collab):
            task = state["task_id"]
            knowledge = await populate_sources(dsn, bindings.config, actors, tmp_path)
            # Controlled old submitted row: no fake binding, job, result or completion is created.
            async with bindings.store.connection() as conn:
                await conn.execute(
                    "UPDATE anlan_v2.collaboration_applications SET "
                    "status='under_review',version=2,reviewer_user_id=%s,"
                    "submitted_material_revision=1 WHERE task_id=%s",
                    (actors[1].user_id, task),
                )
            assert (await collab.get(actors[1], task))["precheck"]["required"]
            assert (await collab.get(actors[1], task))["precheck"]["status"] == "unbound"
            with pytest.raises(InvalidTransition):
                await send(collab, actors[1], task, "complete_review", 2, conclusion="旧卡片")
            await send(
                collab, actors[1], task, "request_changes", 2, questions=["请确认人员与区域"]
            )
            await bindings.confirm(actors[0], task, binding_command())
            submit = await send(collab, actors[0], task, "resubmit", 3, reply="已确认绑定")
            preflight = PreflightService(
                dsn,
                bindings.config,
                bindings.service_context_factory,
                PreflightRunner(
                    FactTools(tmp_path, clock=lambda: bindings.config.as_of),
                    knowledge,
                    clock=lambda: bindings.config.as_of,
                ),
            )
            result = await preflight.process_next(submit["precheck_job_id"])
            assert result["result"]["ready"]
            assert submit["application"]["submitted_material_revision"] == 1

    run(scenario())


def test_pre_p13_changes_requested_can_resubmit_after_confirming_first_binding(
    dsn,  # noqa: F811
    tmp_path,
):
    async def scenario():
        async with setup(dsn, tmp_path) as (bindings, actors, state, collab):
            task = state["task_id"]
            async with bindings.store.connection() as conn:
                await conn.execute(
                    "UPDATE anlan_v2.collaboration_applications SET "
                    "status='changes_requested',version=3,reviewer_user_id=%s,"
                    "submitted_material_revision=1 WHERE task_id=%s",
                    (actors[1].user_id, task),
                )
            # P12 could stop here before creating any P13 cycle row.
            assert (await collab.get(actors[1], task))["precheck"]["status"] == "unbound"
            await bindings.confirm(actors[0], task, binding_command())
            resubmitted = await send(
                collab,
                actors[0],
                task,
                "resubmit",
                3,
                reply="旧申请已确认首个 P13 绑定",
            )
            assert resubmitted["application"]["status"] == "under_review"
            assert resubmitted["application"]["version"] == 4
            assert resubmitted["application"]["submitted_material_revision"] == 1
            assert resubmitted["precheck_job_id"]

    run(scenario())


def test_material_http_waits_for_short_actual_registry_lock(dsn, monkeypatch):  # noqa: F811
    import asyncio
    from contextlib import asynccontextmanager

    from test_collaboration_api import clients, start
    from test_material_revisions import PATCH

    from anlan.common.errors import TaskBusy
    from anlan.infrastructure.postgres import PostgresRegistry

    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            task = (await start(sessions[0]))["task_id"]
            factory = sessions[0]._transport.app.state.preflight.service_context_factory
            busy = asyncio.Event()
            original = PostgresRegistry.locked

            @asynccontextmanager
            async def observed(registry, *args, **kwargs):
                try:
                    async with original(registry, *args, **kwargs) as record:
                        yield record
                except TaskBusy:
                    busy.set()
                    raise

            async with factory() as workflow:
                async with workflow._registry.locked(actors[0], task):
                    with monkeypatch.context() as context:
                        context.setattr(PostgresRegistry, "locked", observed)
                        operation = asyncio.create_task(
                            sessions[0].post(
                                f"/tasks/{task}/revise",
                                json=dict(request_id="material", expected_revision=1, fields=PATCH),
                            )
                        )
                        await asyncio.wait_for(busy.wait(), 5)
            response = await operation
            assert response.status_code == 200, response.text
            assert response.json()["revision"] == 2

    run(scenario())


def test_missing_binding_blocks_submit_and_legacy_unfinished_completion(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (_, actors, state, collab):
            with pytest.raises(InvalidTransition):
                await send(
                    collab,
                    actors[0],
                    state["task_id"],
                    "submit",
                    reviewer_user_id=actors[1].user_id,
                )

    run(scenario())


def test_submission_job_and_notification_roll_back_with_receipt(dsn, tmp_path, monkeypatch):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (bindings, actors, state, collab):
            task = state["task_id"]
            await bindings.confirm(actors[0], task, binding_command())

            async def crash(*args, **kwargs):
                raise RuntimeError("receipt crash")

            with monkeypatch.context() as context:
                context.setattr(collab.store, "save_receipt", crash)
                with pytest.raises(RuntimeError):
                    await send(
                        collab,
                        actors[0],
                        task,
                        "submit",
                        expected_binding_revision=1,
                        reviewer_user_id=actors[1].user_id,
                    )
            async with bindings.store.connection() as conn:
                for table in ("precheck_jobs", "collaboration_events"):
                    row = await (
                        await conn.execute(
                            f"SELECT count(*) AS n FROM anlan_v2.{table} WHERE task_id=%s", (task,)
                        )
                    ).fetchone()
                    assert row["n"] == 0
            assert (await collab.get(actors[0], task))["application"].version == 1

    run(scenario())
