from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401

from anlan.common.errors import InvalidTransition, TaskBusy
from anlan.conversation.contracts import IntentProposal
from anlan.conversation.service import ConversationService
from anlan.infrastructure.conversations import ConversationStore
from anlan.interfaces.conversation_runtime import TaskProjection, WorkflowResult
from anlan.llm.conversation import AssistantReply, ScriptedConversationModel

pytestmark = pytest.mark.postgres


def unique(prefix):
    return f"{prefix}-{uuid4().hex}"


def projection(task_id, *, revision=1, status="waiting_input"):
    return TaskProjection(
        task_id=task_id,
        status=status,
        revision=revision,
        fields={"work_object_description": "V101 管线补焊"},
        missing_fields=[
            "work_location_description",
            "work_method_description",
            "attachment_description",
        ],
        issue_questions=[],
        analysis_mode="offline",
        semantic_status="offline_not_checked",
        recoverable=True,
    )


@dataclass
class FakeWorkflow:
    calls: list = field(default_factory=list)
    tasks: dict = field(default_factory=dict)

    async def start(self, identity, conversation_id, message_id, fields):
        del identity
        self.calls.append(("start", conversation_id, message_id, fields))
        task_id = f"task-{message_id}"
        self.tasks.setdefault(task_id, projection(task_id))
        return WorkflowResult(projection=self.tasks[task_id])

    async def submit(
        self, identity, conversation_id, message_id, task_id, expected_revision, fields, status
    ):
        del identity
        self.calls.append(
            ("submit", conversation_id, message_id, task_id, expected_revision, fields, status)
        )
        self.tasks[task_id] = projection(task_id, revision=expected_revision + 1)
        return WorkflowResult(projection=self.tasks[task_id])

    async def recover(self, identity, task_id):
        del identity
        self.calls.append(("recover", task_id))
        return WorkflowResult(projection=self.tasks[task_id])

    async def read(self, identity, task_id):
        del identity
        return WorkflowResult(projection=self.tasks[task_id])


class CountingFactory:
    def __init__(self, model=None):
        self.model = model or ScriptedConversationModel()
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return type("Pair", (), {"classifier": self.model, "responder": self.model})()


def service(store_dsn):
    workflow = FakeWorkflow()
    factory = CountingFactory()
    return (
        ConversationService(ConversationStore(store_dsn), factory, workflow),
        workflow,
        factory,
    )


class ProposedModel:
    def __init__(self, proposals, *, fail_chat=False):
        self.proposals = list(proposals)
        self.fail_chat = fail_chat

    async def classify(self, context, *, run_id="conversation-classify"):
        del context, run_id
        value = self.proposals.pop(0)
        if isinstance(value, Exception):
            raise value
        return IntentProposal(
            intent=value[0],
            fields=value[1] if len(value) > 1 else {},
            requires_confirmation=value[2] if len(value) > 2 else False,
            user_explanation="test proposal",
            classifier_version="scripted-intent-v1",
        )

    async def respond(self, context, *, run_id="conversation-chat"):
        del context, run_id
        if self.fail_chat:
            raise ValueError("provider details must not escape")
        return AssistantReply(text="测试回复")


def test_candidate_then_confirmation_creates_exactly_one_task(dsn):  # noqa: F811
    async def scenario():
        subject, workflow, factory = service(dsn)
        conversation = await subject.create(OWNER, request_id=unique("create"))
        candidate = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="m1",
            expected_revision=1,
            text="明天在一号罐区 V101 管线上补焊",
        )
        assert candidate["status"] == "pending_confirmation"
        assert candidate["task_projection"] is None
        assert candidate["messages"][0]["status"] == "completed"
        assert await subject.snapshot(OWNER, conversation["conversation_id"]) == candidate
        assert workflow.calls == []

        started = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="m2",
            expected_revision=candidate["revision"],
            text="确认申请",
        )
        assert started["status"] == "active_hot_work"
        assert [call[0] for call in workflow.calls] == ["start"]
        assert started["task_projection"]["task_id"]
        assert factory.calls == 2

    run(scenario())


def test_chat_during_active_task_never_calls_workflow(dsn):  # noqa: F811
    async def scenario():
        subject, workflow, _ = service(dsn)
        conversation = await subject.create(OWNER, request_id=unique("chat"))
        candidate = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="candidate",
            expected_revision=1,
            text="V101 管线补焊",
        )
        active = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="confirm",
            expected_revision=candidate["revision"],
            text="确认申请",
        )
        before = workflow.calls.copy()
        result = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="chat",
            expected_revision=active["revision"],
            text="电焊和气焊有什么区别？",
        )
        assert result["status"] == "active_hot_work"
        assert workflow.calls == before
        assert "业务任务状态以侧栏为准" in result["messages"][-1]["text"]

    run(scenario())


def test_rejection_pause_resume_and_detach_are_server_owned_transitions(dsn):  # noqa: F811
    async def scenario():
        subject, workflow, _ = service(dsn)
        conversation = await subject.create(OWNER, request_id=unique("transitions"))
        candidate = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="candidate",
            expected_revision=1,
            text="V101 补焊",
        )
        rejected = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="reject",
            expected_revision=candidate["revision"],
            text="不是，继续聊",
        )
        assert rejected["status"] == "idle"
        assert workflow.calls == []

        candidate = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="candidate-2",
            expected_revision=rejected["revision"],
            text="V101 补焊",
        )
        active = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="confirm",
            expected_revision=candidate["revision"],
            text="确认申请",
        )
        paused = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="pause",
            expected_revision=active["revision"],
            text="先暂停",
        )
        assert paused["status"] == "paused"
        resumed = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="resume",
            expected_revision=paused["revision"],
            text="继续任务",
        )
        assert resumed["status"] == "active_hot_work"
        detached = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="detach",
            expected_revision=resumed["revision"],
            text="取消当前任务",
        )
        assert detached["status"] == "idle"
        assert detached["active_task_id"] is None
        assert [call[0] for call in workflow.calls] == ["start", "recover"]

    run(scenario())


def test_changed_replay_stale_revision_and_second_pending_message_are_rejected(dsn):  # noqa: F811
    async def scenario():
        subject, _, _ = service(dsn)
        conversation = await subject.create(OWNER, request_id=unique("guards"))
        first = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="first",
            expected_revision=1,
            text="你好",
        )
        replay = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="first",
            expected_revision=1,
            text="你好",
        )
        assert replay == first
        with pytest.raises(InvalidTransition):
            await subject.message(
                OWNER,
                conversation["conversation_id"],
                request_id="first",
                expected_revision=1,
                text="changed",
            )
        with pytest.raises(InvalidTransition):
            await subject.message(
                OWNER,
                conversation["conversation_id"],
                request_id="stale",
                expected_revision=1,
                text="你好",
            )
        pending = await subject.store.reserve_message(
            OWNER, conversation["conversation_id"], "pending", first["revision"], "处理中"
        )
        assert pending["status"] == "pending"
        with pytest.raises(TaskBusy):
            await subject.message(
                OWNER,
                conversation["conversation_id"],
                request_id="second",
                expected_revision=first["revision"] + 1,
                text="第二条",
            )

    run(scenario())


def test_pending_amendment_merges_fields_and_requires_reconfirmation(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("hot_work_candidate", {"work_location_description": "一号罐区"}, True),
                ("confirm_pending_intent",),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("amend"))
        for request_id, text in (("first", "申请"), ("amend", "补充地点")):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        assert state["pending_intent"]["fields"] == {
            "work_object_description": "V101 补焊",
            "work_location_description": "一号罐区",
        }
        confirmed = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="confirm",
            expected_revision=state["revision"],
            text="确认",
        )
        assert workflow.calls[0][3] == state["pending_intent"]["fields"]
        assert confirmed["status"] == "active_hot_work"

    run(scenario())


def test_unambiguous_and_ambiguous_task_input_obey_write_boundary(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                ("task_input_candidate", {"work_location_description": "一号罐区"}, False),
                ("task_input_candidate", {"work_method_description": "可能电焊"}, True),
                ("confirm_pending_intent",),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("input"))
        for request_id in ("candidate", "confirm", "certain"):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=request_id,
            )
        assert [call[0] for call in workflow.calls] == ["start", "submit"]
        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="ambiguous",
            expected_revision=state["revision"],
            text="可能电焊",
        )
        assert [call[0] for call in workflow.calls] == ["start", "submit"]
        assert state["status"] == "pending_confirmation"
        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="confirm-input",
            expected_revision=state["revision"],
            text="确认",
        )
        assert [call[0] for call in workflow.calls] == ["start", "submit", "submit"]
        assert state["status"] == "active_hot_work"

    run(scenario())


@pytest.mark.parametrize(
    ("proposals", "fail_chat", "category"),
    [
        ([ValueError("secret classifier failure")], False, "classifier_failure"),
        ([("casual_chat",)], True, "chat_failure"),
    ],
)
def test_model_failures_are_sanitized_durable_and_make_zero_business_writes(
    dsn, proposals, fail_chat, category  # noqa: F811
):
    async def scenario():
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn),
            CountingFactory(ProposedModel(proposals, fail_chat=fail_chat)),
            workflow,
        )
        conversation = await subject.create(OWNER, request_id=unique("failure"))
        arguments = dict(
            identity=OWNER,
            conversation_id=conversation["conversation_id"],
            request_id="failure",
            expected_revision=1,
            text="不会泄露的输入",
        )
        result = await subject.message(**arguments)
        assert result == {"error_category": category}
        assert await subject.message(**arguments) == result
        assert workflow.calls == []
        assert "secret" not in str(result)

    run(scenario())


def test_policy_conflict_is_durable_and_releases_pending_slot(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel([("confirm_pending_intent",), ("casual_chat",)])
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), FakeWorkflow()
        )
        conversation = await subject.create(OWNER, request_id=unique("policy"))
        invalid = dict(
            identity=OWNER,
            conversation_id=conversation["conversation_id"],
            request_id="invalid",
            expected_revision=1,
            text="确认",
        )
        with pytest.raises(InvalidTransition):
            await subject.message(**invalid)
        with pytest.raises(InvalidTransition):
            await subject.message(**invalid)
        recovered = await subject.message(
            OWNER,
            conversation["conversation_id"],
            request_id="next",
            expected_revision=2,
            text="你好",
        )
        assert recovered["messages"][-1]["role"] == "assistant"

    run(scenario())


def test_workflow_conflict_replay_preserves_exception_semantics(dsn):  # noqa: F811
    async def scenario():
        class ConflictWorkflow(FakeWorkflow):
            async def start(self, *args, **kwargs):
                raise InvalidTransition("task conflict")

        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101"}, True),
                ("confirm_pending_intent",),
            ]
        )
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), ConflictWorkflow()
        )
        state = await subject.create(OWNER, request_id=unique("workflow-conflict"))
        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="candidate",
            expected_revision=1,
            text="申请",
        )
        arguments = dict(
            identity=OWNER,
            conversation_id=state["conversation_id"],
            request_id="confirm",
            expected_revision=state["revision"],
            text="确认",
        )
        with pytest.raises(InvalidTransition):
            await subject.message(**arguments)
        with pytest.raises(InvalidTransition):
            await subject.message(**arguments)

    run(scenario())
