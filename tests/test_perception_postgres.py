import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from test_events import NOW, OWNER, payload
from test_events_postgres import dsn, run, setup  # noqa: F401 -- real PG fixture

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity
from anlan.interfaces.cli import DEMO_PATCHES
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.tool import UnavailableKnowledgeStore
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres
REFS = {"worker_id": "worker-001", "qualification_type": "hot-work", "area_id": "area-p5"}


async def prepared(dsn, model=None, kind="helmet_missing"):  # noqa: F811 -- shared fixture name
    from anlan.infrastructure.perception import PerceptionStore
    from anlan.interfaces.perception_runtime import PerceptionRuntime
    from anlan.llm.perception import ScriptedPerceptionModel

    class EmptyMemory:
        async def list_active(self, identity):
            return []

    store, state, config = await setup(dsn, kind)
    await PerceptionStore(dsn).initialize()
    event = await store.receive(OWNER, config.source_id, payload(kind), config)
    runtime = PerceptionRuntime(
        dsn,
        FactTools(Path("examples/synthetic/facts-v1"), clock=lambda: NOW),
        UnavailableKnowledgeStore(lambda: NOW),
        EmptyMemory(),
        model or ScriptedPerceptionModel(),
        clock=lambda: NOW,
    )
    return runtime, store, state, config, event


@pytest.mark.parametrize("kind", ["helmet_missing", "gas_abnormal"])
def test_event_to_evidence_to_durable_human_feedback(dsn, kind):  # noqa: F811
    async def scenario():
        runtime, store, state, _, event = await prepared(dsn, kind=kind)
        review = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="review")
        assert review["result"]["status"] == "completed" and review["currentness"] == "current"
        assert len(review["result"]["report"]["observations"]) == 3
        assert review["result"]["report"]["candidate"]["event_id"] == "event-1"
        assert await runtime.review(OWNER, event["receipt_id"], REFS, request_id="review") == review
        confirmed = await runtime.feedback(
            OWNER, review["review_id"], 1, "needs_verification", request_id="feedback"
        )
        assert confirmed["revision"] == 2
        assert confirmed["feedback"]["decision"] == "needs_verification"
        assert (
            await runtime.feedback(
                OWNER, review["review_id"], 1, "needs_verification", request_id="feedback"
            )
            == confirmed
        )
        assert (await store.get(OWNER, event["receipt_id"]))["raw"] == event["raw"]
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.get(OWNER, state["task_id"]) == state

    run(scenario())


@pytest.mark.parametrize("change", ["material", "new_event", "expiry"])
def test_old_review_becomes_stale_and_cannot_be_confirmed(dsn, change):  # noqa: F811
    from datetime import timedelta

    async def scenario():
        runtime, store, state, config, event = await prepared(dsn)
        review = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="first")
        if change == "material":
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                await service.resume(OWNER, state["task_id"], 1, DEMO_PATCHES[0])
        elif change == "new_event":
            await store.receive(
                OWNER, config.source_id, payload(event_id="new", sequence=2), config
            )
        else:
            runtime.clock = lambda: NOW + timedelta(minutes=6)
        stale = await runtime.get(OWNER, review["review_id"])
        assert stale["currentness"] != "current"
        assert stale["result"] == review["result"]  # Preserve original candidate as history.
        with pytest.raises(InvalidTransition):
            await runtime.feedback(
                OWNER, review["review_id"], 1, "confirmed_event", request_id="no"
            )

    run(scenario())


def test_identity_object_and_feedback_authority_boundaries(dsn):  # noqa: F811
    async def scenario():
        runtime, _, _, _, event = await prepared(dsn)
        with pytest.raises(InvalidTransition):
            await runtime.review(
                OWNER, event["receipt_id"], REFS | {"area_id": "wrong"}, request_id="wrong"
            )
        stranger = Identity(tenant_id=OWNER.tenant_id, user_id="stranger")
        with pytest.raises(AccessDenied):
            await runtime.review(stranger, event["receipt_id"], REFS, request_id="no")
        review = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="ok")
        with pytest.raises(AccessDenied):
            await runtime.get(stranger, review["review_id"])
        with pytest.raises(ValueError):
            await runtime.feedback(OWNER, review["review_id"], 1, "approve_work", request_id="no")
        outcomes = await asyncio.gather(
            *[
                runtime.feedback(
                    OWNER, review["review_id"], 1, "disputed_event", request_id=uuid4().hex
                )
                for _ in range(2)
            ],
            return_exceptions=True,
        )
        assert sum(isinstance(item, dict) for item in outcomes) == 1
        assert sum(isinstance(item, (InvalidTransition, TaskBusy)) for item in outcomes) == 1

    run(scenario())


def test_concurrent_idempotent_review_calls_model_once(dsn):  # noqa: F811
    from anlan.llm.perception import ScriptedPerceptionModel

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class Blocking(ScriptedPerceptionModel):
            calls = 0

            async def generate(self, context, run_id):
                self.calls += 1
                started.set()
                await release.wait()
                return await super().generate(context, run_id)

        model = Blocking()
        runtime, _, _, _, event = await prepared(dsn, model)
        job = asyncio.create_task(
            runtime.review(OWNER, event["receipt_id"], REFS, request_id="concurrent")
        )
        await asyncio.wait_for(started.wait(), 5)
        pending = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="concurrent")
        assert pending["result"] is None
        with pytest.raises(TaskBusy):
            await runtime.recover(OWNER, pending["review_id"])
        release.set()
        completed = await job
        assert model.calls == 1 and completed["result"]["status"] == "completed"

    run(scenario())


def test_late_model_result_is_retained_but_stale(dsn):  # noqa: F811
    from anlan.llm.perception import ScriptedPerceptionModel

    async def scenario():
        class Changing(ScriptedPerceptionModel):
            async def generate(self, context, run_id):
                await store.receive(
                    OWNER, config.source_id, payload(event_id="new", sequence=2), config
                )
                return await super().generate(context, run_id)

        runtime, store, _, config, event = await prepared(dsn, Changing())
        review = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="late")
        assert review["result"]["status"] == "stale"
        assert review["result"]["report"]["candidate"] is not None
        with pytest.raises(InvalidTransition):
            await runtime.feedback(
                OWNER, review["review_id"], 1, "confirmed_event", request_id="no"
            )

    run(scenario())


def test_model_failure_and_cancel_leave_raw_alarm_and_explicit_review_state(dsn):  # noqa: F811
    async def scenario():
        class Broken:
            mode = "explicit_failure_double"

            async def generate(self, context, run_id):
                raise RuntimeError("model unavailable")

        runtime, store, _, _, event = await prepared(dsn, Broken())
        failed = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="failed")
        assert failed["result"]["status"] == "failed"
        assert len(failed["result"]["report"]["observations"]) == 3

        class Cancelled:
            mode = "explicit_cancel_double"

            async def generate(self, context, run_id):
                raise asyncio.CancelledError

        runtime.model = Cancelled()
        with pytest.raises(asyncio.CancelledError):
            await runtime.review(OWNER, event["receipt_id"], REFS, request_id="cancelled")
        record = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="cancelled")
        assert record["result"]["status"] == "cancelled"
        assert (await store.get(OWNER, event["receipt_id"]))["raw"]["alarm_state"] == "active"

    run(scenario())


def test_interrupted_review_recovers_without_resending_model(dsn, monkeypatch):  # noqa: F811
    from anlan.infrastructure.perception import PerceptionStore

    async def scenario():
        runtime, _, _, _, event = await prepared(dsn)

        async def crash(*args, **kwargs):
            raise RuntimeError("persist result crash")

        with monkeypatch.context() as context:
            context.setattr(PerceptionStore, "finish", crash)
            with pytest.raises(RuntimeError):
                await runtime.review(OWNER, event["receipt_id"], REFS, request_id="interrupted")
        pending = await runtime.review(OWNER, event["receipt_id"], REFS, request_id="interrupted")
        assert pending["result"] is None
        recovered = await runtime.recover(OWNER, pending["review_id"])
        assert recovered["result"]["status"] == "interrupted"
        assert recovered["result"]["report"]["model_resubmitted"] is False

    run(scenario())


def test_model_phase_cancel_cannot_be_confirmed(dsn):  # noqa: F811
    from anlan.llm.perception import ScriptedPerceptionModel

    async def scenario():
        signal = asyncio.Event()

        class Cancelling(ScriptedPerceptionModel):
            async def generate(self, context, run_id):
                signal.set()
                return await super().generate(context, run_id)

        runtime, _, _, _, event = await prepared(dsn, Cancelling())
        review = await runtime.review(
            OWNER, event["receipt_id"], REFS, request_id="cancel-model", cancel_event=signal
        )
        assert review["result"]["status"] == "cancelled"
        with pytest.raises(InvalidTransition):
            await runtime.feedback(
                OWNER, review["review_id"], 1, "confirmed_event", request_id="not-allowed"
            )

    run(scenario())


@pytest.mark.parametrize("change_material", [False, True])
def test_parent_cancel_in_collection_preserves_completed_observations(
    dsn,  # noqa: F811 -- shared real PG fixture
    change_material,
):
    async def scenario():
        runtime, _, state, _, event = await prepared(dsn)
        completed, entered = asyncio.Event(), asyncio.Event()
        base = runtime.tools

        class Facts:
            clock = staticmethod(lambda: NOW)
            query_worker_qualification = base.query_worker_qualification

            async def query_area_status(self, *args):
                value = await base.query_area_status(*args)
                completed.set()
                return value

        class SlowKnowledge:
            async def search(self, *args):
                entered.set()
                await asyncio.sleep(10)

        runtime.tools, runtime.knowledge = Facts(), SlowKnowledge()
        job = asyncio.create_task(
            runtime.review(OWNER, event["receipt_id"], REFS, request_id="cancel-collection")
        )
        await asyncio.wait_for(completed.wait(), 5)
        await entered.wait()
        if change_material:
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                await service.resume(OWNER, state["task_id"], 1, DEMO_PATCHES[0])
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        saved = await runtime.review(
            OWNER, event["receipt_id"], REFS, request_id="cancel-collection"
        )
        observations = saved["result"]["report"]["observations"]
        assert saved["result"]["status"] == "cancelled" and len(observations) == 3
        assert all(o["reason"] == "access_denied" for o in observations[:2])
        assert observations[2]["reason"] == "parent_cancelled"

    run(scenario())
