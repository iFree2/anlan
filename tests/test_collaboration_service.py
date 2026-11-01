"""Lock, rollback, recovery, replay and projection contracts on real PostgreSQL."""

import asyncio

import pytest
from test_collaboration_api import clients, command, completion, send, settings, start
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import COMPLETE, PATCH

from anlan.collaboration.service import CollaborationService
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.interfaces.conversation_runtime import WorkflowAdapter
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres


async def counts(dsn, tenant):  # noqa: F811
    async with await CollaborationStore(dsn)._connect() as conn:
        values = []
        for table in ("applications", "events", "notifications", "commands"):
            cursor = await conn.execute(
                f"SELECT count(*) AS n FROM anlan_v2.collaboration_{table} WHERE tenant_id=%s",
                (tenant,))
            values.append((await cursor.fetchone())["n"])
        return values


def test_command_replay_and_payload_conflict(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            body = command(reviewer_user_id="reviewer")
            first = await send(applicant, task, "submit", body)
            assert await send(applicant, task, "submit", body) == first
            for mutation in ({"reviewer_user_id": "unassigned"},
                             {"expected_material_revision": 2},
                             {"expected_application_version": 2}):
                await send(applicant, task, "submit", body | mutation, 409)
            other = (await start(applicant))["task_id"]
            await send(applicant, other, "submit", body, 409)
            await send(reviewer, task, "request_changes", command(2, questions=["说明点位"]))
            # Replay after state advances still returns the original committed receipt.
            assert await send(applicant, task, "submit", body) == first
            assert await counts(dsn, actors[0].tenant_id) == [2, 2, 2, 2]
    run(scenario())


def test_transaction_failure_has_no_partial_notification(dsn, monkeypatch):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            applicant = sessions[0]
            task = (await start(applicant))["task_id"]
            body = command(reviewer_user_id="reviewer")
            assert hasattr(CollaborationStore, "save_receipt"), "atomic receipt boundary missing"
            original = CollaborationStore.save_receipt

            async def broken(*args, **kwargs):
                raise RuntimeError("crash immediately before receipt")

            with monkeypatch.context() as context:
                context.setattr(CollaborationStore, "save_receipt", broken)
                with pytest.raises(RuntimeError, match="before receipt"):
                    await send(applicant, task, "submit", body)
            assert await counts(dsn, actors[0].tenant_id) == [1, 0, 0, 0]
            path = f"/collaboration/applications/{task}"
            assert (await applicant.get(path)).json()["application"]["version"] == 1
            assert CollaborationStore.save_receipt is original
            await send(applicant, task, "submit", body)
            assert await counts(dsn, actors[0].tenant_id) == [1, 1, 1, 1]
    run(scenario())


def test_concurrent_edit_and_completion_conflict(dsn):  # noqa: F811
    async def scenario():
        config = settings()
        async with clients(dsn, config) as (sessions, actors, trusted):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            # Hold exactly the registry/checkpointer session lock used by material execution.
            async with postgres_service(dsn, OfflineAnalyzer(), access_config=trusted) as service:
                async with service._registry.locked(actors[0], task):
                    await send(reviewer, task, "complete_review", command(
                        2, conclusion="已核对"), 409)
            body = await completion(reviewer, task, command(2, conclusion='人工核对'))
            # Distinct requests still contend on the one real task/application version.
            results = await asyncio.gather(*[reviewer.post(
                f"/collaboration/applications/{task}/commands/complete_review",
                json=body | {'request_id': str(i)}) for i in range(2)])
            assert sorted(r.status_code for r in results) == [200, 409]
            async with postgres_service(dsn, OfflineAnalyzer(), access_config=trusted) as service:
                with pytest.raises(InvalidTransition):
                    await service.revise(actors[0], task, 1, PATCH)
            assert await counts(dsn, actors[0].tenant_id) == [1, 2, 2, 2]
    run(scenario())


def test_pending_material_recovery_cannot_finalize(dsn, monkeypatch):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, trusted):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            async with postgres_service(dsn, OfflineAnalyzer(), access_config=trusted) as service:
                async def broken(*args, **kwargs):
                    raise RuntimeError("checkpoint operation interrupted")
                with monkeypatch.context() as context:
                    context.setattr(service._registry, "complete", broken)
                    with pytest.raises(RuntimeError):
                        await service.revise(actors[0], task, 1, PATCH, request_id="pending")
            await send(applicant, task, "submit", command(1, 2, reviewer_user_id="reviewer"), 409)
            assert (await applicant.post(f"/tasks/{task}/recover")).status_code == 200
            await send(applicant, task, "submit", command(1, 2, reviewer_user_id="reviewer"))
            # Corrupt/incomplete old writer cannot be silently treated as finalizable.
            async with await CollaborationStore(dsn)._connect() as conn:
                await conn.execute("UPDATE anlan_v2.anlan_operations SET result=NULL "
                                   "WHERE task_id=%s AND request_id='pending'", (task,))
            await send(reviewer, task, "complete_review", command(2, 2, conclusion="已核对"), 409)
            assert (await applicant.post(f"/tasks/{task}/recover")).status_code == 409
    run(scenario())


def test_direct_workflow_graph_and_conversation_adapter_cannot_bypass_freeze(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, trusted):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            # Even old compositions lacking a role resolver must enforce persisted freeze.
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                for method, args in [(service.revise, (1, PATCH)),
                                     (service.resume, (1, PATCH)), (service.recover, ())]:
                    with pytest.raises(InvalidTransition):
                        await method(actors[0], task, *args)
                state = await CollaborationService._bounded_lock(
                    lambda: service.get(actors[0], task)
                )
                with pytest.raises((AccessDenied, InvalidTransition)):
                    await service._graph.ainvoke(state, {"configurable": {
                        "thread_id": state["thread_id"]}})
                with pytest.raises((AccessDenied, InvalidTransition)):
                    await service._graph.aupdate_state({"configurable": {
                        "thread_id": state["thread_id"]}}, {"fields": COMPLETE | PATCH})
            adapter = WorkflowAdapter(lambda: postgres_service(
                dsn, OfflineAnalyzer(), access_config=trusted))
            with pytest.raises(InvalidTransition):
                await adapter.submit(actors[0], "private", "m", task, 1, PATCH, "awaiting_review")
            with pytest.raises(AccessDenied):
                await adapter.start(actors[1], "private", "m", COMPLETE)
    run(scenario())


def test_notifications_reauthorize_role_and_participation(dsn):  # noqa: F811
    async def scenario():
        config, actors, tokens = settings()
        async with clients(dsn, (config, actors, tokens)) as (sessions, _, _):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            inbox = (await sessions[1].get("/collaboration/notifications")).json()
            assert len(inbox["items"]) == 1
            cursor = inbox["next_cursor"]
            assert (await sessions[1].get("/collaboration/notifications", params={
                "after": cursor})).json()["items"] == []
            assert (await sessions[2].get("/collaboration/notifications", params={
                "after": 0})).json()["items"] == []
            async with await CollaborationStore(dsn)._connect() as conn:
                await conn.execute("UPDATE anlan_v2.collaboration_applications "
                                   "SET reviewer_user_id='unassigned' WHERE task_id=%s", (task,))
            assert (await sessions[1].get("/collaboration/notifications")).json()["items"] == []
        changed = config.model_copy(update={"tokens": [g.model_copy(update={
            "collaboration_role": None}) if g.identity == actors[1] else g for g in config.tokens]})
        async with clients(dsn, (changed, actors, tokens)) as (sessions, _, _):
            assert (await sessions[1].get("/collaboration/notifications")).status_code == 404
    run(scenario())


def test_replay_compares_complete_payload_including_text_whitespace(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            body = command(2, questions=["请说明点位"])
            await send(sessions[1], task, "request_changes", body)
            await send(sessions[1], task, "request_changes", body | {
                "questions": ["请说明点位 "]}, 409)
    run(scenario())


@pytest.mark.parametrize("change", ["missing", "failed", "error", "revision", "contract"])
def test_real_checkpoint_readiness_and_versions_are_required(dsn, change):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, trusted):
            state = await start(sessions[0], fields={} if change == "missing" else COMPLETE)
            task = state["task_id"]
            if change in {"failed", "error"}:
                # Authorized test writer changes the real checkpoint, not a cached projection.
                async with postgres_service(
                        dsn, OfflineAnalyzer(), access_config=trusted) as service:
                    async with service._registry.locked(
                            actors[0], task, action="edit_materials") as record:
                        await service._graph.aupdate_state(service._config(record), {
                            "analysis": {"semantic_status": "failed" if change == "failed"
                                         else "checked", "error": "analysis failure",
                                         "issues": []}})
            if change == "contract":
                async with await CollaborationStore(dsn)._connect() as conn:
                    await conn.execute("UPDATE anlan_v2.anlan_tasks "
                                       "SET contract_version='incompatible' WHERE task_id=%s",
                                       (task,))
            await send(sessions[0], task, "submit", command(
                1, 2 if change == "revision" else 1, reviewer_user_id="reviewer"), 409)
            assert await counts(dsn, actors[0].tenant_id) == [1, 0, 0, 0]
    run(scenario())


def test_resubmit_requires_new_revision_and_preserves_reviewer(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            await send(sessions[1], task, "request_changes", command(2, questions=["补充方式"]))
            await send(sessions[0], task, "resubmit", command(3, reply="口头补充"), 409)
            await send(sessions[0], task, "resubmit", command(
                3, reply="伪造重派", reviewer_user_id="unassigned"), 422)
            assert await counts(dsn, actors[0].tenant_id) == [1, 2, 2, 2]
    run(scenario())


def test_start_registration_and_checkpoint_crash_recover_in_same_task(dsn, monkeypatch):  # noqa: F811
    async def scenario():
        from anlan.workflows.service import start_task_id

        config, actors, _ = settings()
        await CollaborationStore(dsn).initialize()
        task = start_task_id(actors[0], "crash-window")
        async with postgres_service(dsn, OfflineAnalyzer(), access_config=config) as service:
            async def broken(*args, **kwargs):
                raise RuntimeError("crash before material reserve")
            with monkeypatch.context() as context:
                context.setattr(service._registry, "reserve", broken)
                with pytest.raises(RuntimeError):
                    await service.start(actors[0], COMPLETE, request_id="crash-window")
        assert (await CollaborationStore(dsn).get(actors[0], "applicant", task)).status == "draft"
        async with postgres_service(dsn, OfflineAnalyzer(), access_config=config) as fresh:
            assert (await fresh.recover(actors[0], task))["task_id"] == task
        assert await counts(dsn, actors[0].tenant_id) == [1, 0, 0, 0]
    run(scenario())


def test_cross_task_concurrent_request_reuse_has_one_atomic_winner(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            tasks = [(await start(sessions[0]))["task_id"] for _ in range(2)]
            body = command(reviewer_user_id="reviewer", expected_binding_revision=1)
            responses = await asyncio.gather(*[sessions[0].post(
                f"/collaboration/applications/{task}/commands/submit", json=body)
                for task in tasks])
            assert sorted(r.status_code for r in responses) == [200, 409]
            assert await counts(dsn, actors[0].tenant_id) == [2, 1, 1, 1]
    run(scenario())


def test_busy_task_does_not_disclose_existence_to_nonparticipant(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, trusted):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            async with postgres_service(dsn, OfflineAnalyzer(), access_config=trusted) as service:
                async with service._registry.locked(actors[0], task):
                    for client in sessions[2:]:
                        response = await client.get(f"/tasks/{task}")
                        assert response.status_code == 404, response.text
    run(scenario())


def test_reviewer_identifier_cannot_normalize_to_a_different_storage_recipient(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer "), 404)
            assert await counts(dsn, actors[0].tenant_id) == [1, 0, 0, 0]
    run(scenario())


async def wait_for_commit_or_advisory_wait(store, pid, operation):
    """Observe PG lock state, never infer ordering from a timed sleep."""
    async with asyncio.timeout(10), store.connection() as conn:
        while not operation.done():
            cursor = await conn.execute(
                "SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND NOT granted",
                (pid,))
            if await cursor.fetchone():
                return True
        await operation  # Surface unexpected request failures before making assertions.
        return False


@pytest.mark.parametrize("outcome", ["commit", "rollback", "different_recipient"])
def test_notification_cursor_handles_controlled_cross_task_commits(
        dsn, monkeypatch, outcome):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            first_task, second_task = [(await start(sessions[0]))["task_id"] for _ in range(2)]
            store = CollaborationStore(dsn)
            first_inserted, release_first, second_entered = (
                asyncio.Event(), asyncio.Event(), asyncio.Event())
            second_pid = None
            original_receipt = CollaborationStore.save_receipt
            original_append = CollaborationStore.append_event

            async def pause_before_receipt(conn, actor, role, task, action, body, result):
                if task == first_task:
                    # The ordinal exists but is not yet committed or visible to the inbox.
                    first_inserted.set()
                    await release_first.wait()
                    if outcome == "rollback":
                        raise RuntimeError("controlled notification rollback")
                await original_receipt(conn, actor, role, task, action, body, result)

            async def observe_second(conn, actor, role, application, *args):
                nonlocal second_pid
                if application.task_id == second_task:
                    second_pid = conn.info.backend_pid
                    second_entered.set()
                await original_append(conn, actor, role, application, *args)

            with monkeypatch.context() as context:
                context.setattr(CollaborationStore, "save_receipt", staticmethod(
                    pause_before_receipt))
                context.setattr(CollaborationStore, "append_event", staticmethod(observe_second))
                first = asyncio.create_task(send(sessions[0], first_task, "submit", command(
                    reviewer_user_id="reviewer")))
                second = None
                try:
                    async with asyncio.timeout(10):
                        await first_inserted.wait()
                    second_recipient = "unassigned" if outcome == "different_recipient" else (
                        "reviewer")
                    second_body = command(reviewer_user_id=second_recipient)
                    second = asyncio.create_task(send(
                        sessions[0], second_task, "submit", second_body))
                    async with asyncio.timeout(10):
                        await second_entered.wait()
                    blocked = await wait_for_commit_or_advisory_wait(store, second_pid, second)
                    before = (await sessions[1].get("/collaboration/notifications")).json()
                finally:
                    release_first.set()
                    operations = [first] + ([second] if second else [])
                    async with asyncio.timeout(10):
                        results = await asyncio.gather(*operations, return_exceptions=True)

            if outcome == "rollback":
                assert isinstance(results[0], RuntimeError)
                assert str(results[0]) == "controlled notification rollback"
                assert blocked, "same-recipient writer must wait for rollback to release its lock"
                expected = {results[1]["event_id"]}
                assert await counts(dsn, actors[0].tenant_id) == [2, 1, 1, 1]
                path = f"/collaboration/applications/{first_task}"
                assert (await sessions[0].get(path)).json()["application"]["status"] == "draft"
            elif outcome == "different_recipient":
                assert not blocked, "different inboxes must commit independently"
                assert isinstance(results[0], dict) and isinstance(results[1], dict)
                assert before["items"] == []
                other_inbox = (await sessions[2].get("/collaboration/notifications")).json()
                assert [n["event"]["event_id"] for n in other_inbox["items"]] == [
                    results[1]["event_id"]]
                expected = {results[0]["event_id"]}
            else:
                assert all(isinstance(result, dict) for result in results)
                expected = {result["event_id"] for result in results}

            after = (await sessions[1].get("/collaboration/notifications", params={
                "after": before["next_cursor"]})).json()
            delivered = [n["event"]["event_id"] for page in (before, after) for n in page["items"]]
            assert set(delivered) == expected, "advancing the inbox cursor lost a late commit"
            assert len(delivered) == len(expected)
            if outcome != "different_recipient":
                # Replaying the committed command must not create another notification.
                assert await send(sessions[0], second_task, "submit", second_body) == results[1]
                assert (await sessions[1].get("/collaboration/notifications", params={
                    "after": after["next_cursor"]})).json()["items"] == []
    run(scenario())
