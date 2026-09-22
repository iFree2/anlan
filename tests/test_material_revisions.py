"""Explicit revision of completed material analysis, never a fabricated resume."""

from uuid import uuid4

import pytest
from test_events_postgres import dsn, run  # noqa: F401 -- real PG fixture

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity
from anlan.interfaces.cli import DEMO_FIELDS, DEMO_PATCHES
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres
OWNER = Identity(tenant_id="synthetic-p5-revise", user_id="owner")
COMPLETE = DEMO_FIELDS | DEMO_PATCHES[0] | DEMO_PATCHES[1]
PATCH = {"work_method_description": "SYNTHETIC：更换为手工打磨，需重新核对材料"}


def test_explicit_revise_preserves_task_and_generates_new_version(dsn):  # noqa: F811
    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            original = await service.start(OWNER, COMPLETE)
            assert original["status"] == "awaiting_review"
            with pytest.raises(InvalidTransition):
                await service.resume(OWNER, original["task_id"], 1, PATCH)
            revised = await service.revise(
                OWNER, original["task_id"], 1, PATCH, request_id="change"
            )
            assert revised["task_id"] == original["task_id"]
            assert revised["thread_id"] == original["thread_id"]
            assert revised["run_id"] != original["run_id"] and revised["revision"] == 2
            assert revised["fields"] == original["fields"] | PATCH
            assert revised["status"] == "awaiting_review"
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert (
                await service.revise(OWNER, original["task_id"], 1, PATCH, request_id="change")
                == revised
            )
            with pytest.raises(InvalidTransition):
                await service.resume(OWNER, original["task_id"], 1, PATCH, request_id="change")
            with pytest.raises(InvalidTransition):
                await service.revise(OWNER, original["task_id"], 1, PATCH, request_id="stale")
            history = await service.history(OWNER, original["task_id"])
            assert [h["kind"] for h in history] == ["start", "revise"]

    run(scenario())


def test_revise_cannot_bypass_waiting_input_ownership_or_mode(dsn):  # noqa: F811
    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            waiting = await service.start(OWNER, DEMO_FIELDS)
            with pytest.raises(InvalidTransition):
                await service.revise(OWNER, waiting["task_id"], 1, PATCH)
            final = await service.start(OWNER, COMPLETE)
            with pytest.raises(AccessDenied):
                await service.revise(
                    Identity(tenant_id=OWNER.tenant_id, user_id="stranger"),
                    final["task_id"],
                    1,
                    PATCH,
                )
        async with postgres_service(dsn, OfflineAnalyzer(), mode="deepseek") as service:
            with pytest.raises(InvalidTransition):
                await service.revise(OWNER, final["task_id"], 1, PATCH)

    run(scenario())


@pytest.mark.parametrize("crash_at", ["before_graph", "analysis", "completion"])
def test_revise_recovers_without_second_merge(dsn, monkeypatch, crash_at):  # noqa: F811
    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            original = await service.start(OWNER, COMPLETE)

        class BrokenAnalyzer:
            async def analyze(self, application):
                raise RuntimeError("revision analysis crash")

        async def broken(*args, **kwargs):
            raise RuntimeError("revision boundary crash")

        analyzer = BrokenAnalyzer() if crash_at == "analysis" else OfflineAnalyzer()
        async with postgres_service(dsn, analyzer) as service:
            with monkeypatch.context() as context:
                if crash_at == "before_graph":
                    context.setattr(service._graph, "ainvoke", broken)
                elif crash_at == "completion":
                    context.setattr(service._registry, "complete", broken)
                with pytest.raises(RuntimeError):
                    await service.revise(OWNER, original["task_id"], 1, PATCH, request_id="revise")
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            recovered = await service.recover(OWNER, original["task_id"])
            assert recovered["revision"] == 2 and recovered["fields"] == COMPLETE | PATCH
            assert (
                await service.revise(OWNER, original["task_id"], 1, PATCH, request_id="revise")
                == recovered
            )
            assert len(await service.history(OWNER, original["task_id"])) == 2

    run(scenario())


def test_revise_to_missing_fields_enters_normal_interrupt_cycle(dsn):  # noqa: F811
    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            original = await service.start(OWNER, COMPLETE)
            revised = await service.revise(
                OWNER,
                original["task_id"],
                1,
                {"work_method_description": ""},
                request_id=uuid4().hex,
            )
            assert revised["revision"] == 2 and revised["status"] == "waiting_input"
            final = await service.resume(OWNER, original["task_id"], 2, PATCH)
            assert final["revision"] == 3 and final["status"] == "awaiting_review"

    run(scenario())
