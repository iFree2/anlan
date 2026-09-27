import asyncio

import pytest
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401 -- PG fixture
from test_material_revisions import COMPLETE
from test_perception_postgres import REFS, prepared

from anlan.common.errors import InvalidTransition, TaskBusy
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres


def test_start_request_is_idempotent_after_reconnect_and_rejects_changed_payload(dsn):  # noqa: F811
    from uuid import uuid4

    async def scenario():
        request = uuid4().hex
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            initial = await service.start(OWNER, COMPLETE, request_id=request)
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.start(OWNER, COMPLETE, request_id=request) == initial
            with pytest.raises(InvalidTransition):
                await service.start(
                    OWNER, COMPLETE | {"work_method_description": "changed"}, request_id=request
                )
            assert len(await service.history(OWNER, initial["task_id"])) == 1

    run(scenario())


def test_concurrent_start_request_creates_one_task_and_analysis(dsn):  # noqa: F811
    from uuid import uuid4

    async def scenario():
        request, entered, release = uuid4().hex, asyncio.Event(), asyncio.Event()

        class Slow(OfflineAnalyzer):
            calls = 0

            async def analyze(self, application):
                self.calls += 1
                entered.set()
                await release.wait()
                return await super().analyze(application)

        model = Slow()
        async with postgres_service(dsn, model) as first, postgres_service(dsn, model) as second:
            job = asyncio.create_task(first.start(OWNER, COMPLETE, request_id=request))
            await entered.wait()
            with pytest.raises(TaskBusy):
                await second.start(OWNER, COMPLETE, request_id=request)
            release.set()
            result = await job
            assert await second.start(OWNER, COMPLETE, request_id=request) == result
            assert model.calls == 1

    run(scenario())


def test_persistent_cancel_stops_active_review_and_survives_reconnect(dsn):  # noqa: F811
    from anlan.interfaces.perception_runtime import PerceptionRuntime
    from anlan.llm.perception import ScriptedPerceptionModel

    async def scenario():
        entered = asyncio.Event()

        class Slow(ScriptedPerceptionModel):
            async def generate(self, context, run_id):
                entered.set()
                await asyncio.sleep(10)
                return await super().generate(context, run_id)

        runtime, _, _, _, event = await prepared(dsn, Slow())
        job = asyncio.create_task(
            runtime.review(OWNER, event["receipt_id"], REFS, request_id="persistent-cancel")
        )
        await asyncio.wait_for(entered.wait(), 5)
        pending = await runtime.review(
            OWNER, event["receipt_id"], REFS, request_id="persistent-cancel"
        )
        other = PerceptionRuntime(dsn, clock=runtime.clock)
        cancelled = await other.cancel(OWNER, pending["review_id"])
        assert cancelled["cancel_requested"] is True
        result = await asyncio.wait_for(job, 3)
        assert result["result"]["status"] == "cancelled"
        assert (await other.get(OWNER, pending["review_id"]))["cancel_requested"] is True

    run(scenario())


def test_cancelled_interrupted_review_recovers_as_cancelled_without_model(dsn, monkeypatch):  # noqa: F811
    from anlan.infrastructure.perception import PerceptionStore

    async def scenario():
        runtime, _, _, _, event = await prepared(dsn)

        async def crash(*args, **kwargs):
            raise RuntimeError("before result commit")

        with monkeypatch.context() as context:
            context.setattr(PerceptionStore, "finish", crash)
            with pytest.raises(RuntimeError):
                await runtime.review(OWNER, event["receipt_id"], REFS, request_id="interrupted")
        pending = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="interrupted")
        await runtime.cancel(OWNER, pending["review_id"])
        recovered = await runtime.recover(OWNER, pending["review_id"])
        assert recovered["result"]["status"] == "cancelled"
        assert recovered["result"]["report"]["model_resubmitted"] is False

    run(scenario())
