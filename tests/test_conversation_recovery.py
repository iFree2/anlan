from uuid import uuid4

import pytest
from test_conversation_service import CountingFactory, FakeWorkflow
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401

from anlan.conversation.service import ConversationService
from anlan.infrastructure.conversations import ConversationStore
from anlan.llm.conversation import ScriptedConversationModel

pytestmark = pytest.mark.postgres


class Crash(BaseException):
    pass


class CrashClassifier(ScriptedConversationModel):
    def __init__(self):
        self.calls = 0

    async def classify(self, context, *, run_id="conversation-classify"):
        self.calls += 1
        if self.calls == 1:
            raise Crash("after reservation")
        return await super().classify(context, run_id=run_id)


class CrashAfterRouteStore(ConversationStore):
    def __init__(self, store_dsn):
        super().__init__(store_dsn)
        self.crashed = False

    async def save_route(self, *args, **kwargs):
        await super().save_route(*args, **kwargs)
        if not self.crashed:
            self.crashed = True
            raise Crash("after route")


class CrashBeforeBindStore(ConversationStore):
    def __init__(self, store_dsn):
        super().__init__(store_dsn)
        self.crashed = False

    async def bind_task(self, *args, **kwargs):
        if not self.crashed:
            self.crashed = True
            raise Crash("before bind")
        return await super().bind_task(*args, **kwargs)


class ArmedCrashStore(ConversationStore):
    def __init__(self, store_dsn, method):
        super().__init__(store_dsn)
        self.method = method
        self.armed = False

    async def append_assistant_message(self, *args, **kwargs):
        if self.armed and self.method == "assistant":
            self.armed = False
            raise Crash("after state transition")
        return await super().append_assistant_message(*args, **kwargs)

    async def confirm_pending_intent(self, *args, **kwargs):
        if self.armed and self.method == "confirm":
            self.armed = False
            raise Crash("after workflow submit")
        return await super().confirm_pending_intent(*args, **kwargs)


def test_retry_after_reservation_reclassifies_once_and_finishes(dsn):  # noqa: F811
    async def scenario():
        model = CrashClassifier()
        factory = CountingFactory(model)
        store = ConversationStore(dsn)
        subject = ConversationService(store, factory, FakeWorkflow())
        conversation = await subject.create(OWNER, request_id=f"reserve-{uuid4().hex}")
        with pytest.raises(Crash):
            await subject.message(
                OWNER,
                conversation["conversation_id"],
                request_id="message",
                expected_revision=1,
                text="你好",
            )
        result = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="message",
            expected_revision=1,
            text="你好",
        )
        assert result["messages"][-1]["role"] == "assistant"
        assert model.calls == 2

    run(scenario())


def test_retry_after_route_persistence_skips_reclassification(dsn):  # noqa: F811
    async def scenario():
        model = ScriptedConversationModel()
        classifier_calls = 0

        class Counted(ScriptedConversationModel):
            async def classify(self, context, *, run_id="conversation-classify"):
                nonlocal classifier_calls
                classifier_calls += 1
                return await model.classify(context, run_id=run_id)

        store = CrashAfterRouteStore(dsn)
        subject = ConversationService(store, CountingFactory(Counted()), FakeWorkflow())
        conversation = await subject.create(OWNER, request_id=f"route-{uuid4().hex}")
        arguments = dict(
            identity=OWNER,
            conversation_id=conversation["conversation_id"],
            request_id="candidate",
            expected_revision=1,
            text="V101 补焊",
        )
        with pytest.raises(Crash):
            await subject.message(**arguments)
        result = await subject.message(**arguments)
        assert result["status"] == "pending_confirmation"
        assert classifier_calls == 1

    run(scenario())


def test_retry_after_task_creation_binds_same_task_once_without_reclassifying(dsn):  # noqa: F811
    async def scenario():
        store = CrashBeforeBindStore(dsn)
        workflow = FakeWorkflow()
        factory = CountingFactory()
        subject = ConversationService(store, factory, workflow)
        conversation = await subject.create(OWNER, request_id=f"bind-{uuid4().hex}")
        candidate = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="candidate",
            expected_revision=1,
            text="V101 补焊",
        )
        arguments = dict(
            identity=OWNER,
            conversation_id=conversation["conversation_id"],
            request_id="confirm",
            expected_revision=candidate["revision"],
            text="确认申请",
        )
        with pytest.raises(Crash):
            await subject.message(**arguments)
        result = await subject.message(**arguments)
        start_calls = [call for call in workflow.calls if call[0] == "start"]
        assert len(workflow.tasks) == 1
        assert len(start_calls) == 2
        assert start_calls[0][2] == start_calls[1][2]
        assert result["active_task_id"] == next(iter(workflow.tasks))
        snapshot = await ConversationStore(dsn).get(OWNER, conversation["conversation_id"])
        assert len(snapshot["routes"]) == 2

    run(scenario())


def test_retry_after_pending_intent_write_reuses_same_intent(dsn):  # noqa: F811
    async def scenario():
        store = ArmedCrashStore(dsn, "assistant")
        subject = ConversationService(store, CountingFactory(), FakeWorkflow())
        conversation = await subject.create(OWNER, request_id=f"pending-{uuid4().hex}")
        arguments = dict(
            identity=OWNER,
            conversation_id=conversation["conversation_id"],
            request_id="candidate",
            expected_revision=1,
            text="V101 补焊",
        )
        store.armed = True
        with pytest.raises(Crash):
            await subject.message(**arguments)
        before = await store.get(OWNER, conversation["conversation_id"])
        result = await subject.message(**arguments)
        assert result["pending_intent"]["intent_id"] == before["pending_intent"]["intent_id"]
        assert result["pending_intent"]["revision"] == 1

    run(scenario())


def test_retry_after_task_input_write_uses_original_task_revision(dsn):  # noqa: F811
    async def scenario():
        from test_conversation_service import ProposedModel

        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                ("task_input_candidate", {"work_location_description": "一号罐区"}, True),
                ("confirm_pending_intent",),
            ]
        )
        store = ArmedCrashStore(dsn, "confirm")
        workflow = FakeWorkflow()
        subject = ConversationService(store, CountingFactory(model), workflow)
        state = await subject.create(OWNER, request_id=f"input-{uuid4().hex}")
        for request_id, text in (
            ("candidate", "candidate"),
            ("start", "确认申请"),
            ("input", "input"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        arguments = dict(
            identity=OWNER,
            conversation_id=state["conversation_id"],
            request_id="confirm-input",
            expected_revision=state["revision"],
            text="确认",
        )
        store.armed = True
        with pytest.raises(Crash):
            await subject.message(**arguments)
        result = await subject.message(**arguments)
        submit_calls = [call for call in workflow.calls if call[0] == "submit"]
        assert len(submit_calls) == 2
        assert submit_calls[0][4] == submit_calls[1][4] == 1
        assert result["status"] == "active_hot_work"

    run(scenario())
