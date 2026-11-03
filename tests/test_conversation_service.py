from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.conversation.contracts import ConversationState, IntentProposal
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
        if task_id not in self.tasks:
            raise AccessDenied("task is not owned by this identity")
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
            target_task_id=value[3] if len(value) > 3 else None,
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


@pytest.mark.parametrize("text", ["不确认", "还没确认", "解释一下确认流程"])
def test_host_requires_explicit_affirmative_for_hot_work_pending(dsn, text):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("host-confirm-hot"))
        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="candidate",
            expected_revision=state["revision"],
            text="申请",
        )
        pending = state["pending_intent"]

        result = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="misreported-confirm",
            expected_revision=state["revision"],
            text=text,
        )

        assert result["pending_intent"] == pending
        assert result["active_task_id"] is None
        assert workflow.calls == []

    run(scenario())


def test_context_trims_store_history_before_constructing_the_model_contract():
    raw = {
        "messages": [
            {"role": "user", "text": f"message-{index}"} for index in range(101)
        ]
    }
    state = ConversationState(conversation_id="conv-1", revision=1)

    bounded = ConversationService._context(raw, state, None)

    assert [message.text for message in bounded.messages] == [
        f"message-{index}" for index in range(89, 101)
    ]


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
            text="今天心情不错，随便聊聊",
        )
        assert result["status"] == "active_hot_work"
        assert workflow.calls == before
        assert "业务任务状态以侧栏为准" in result["messages"][-1]["text"]

    run(scenario())


def test_negated_active_field_never_calls_workflow(dsn):  # noqa: F811
    async def scenario():
        subject, workflow, _ = service(dsn)
        conversation = await subject.create(OWNER, request_id=unique("negative-field"))
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
            request_id="negated-field",
            expected_revision=active["revision"],
            text="不要把位置改成二号罐区",
        )
        assert workflow.calls == before
        assert result["active_task_id"] == active["active_task_id"]
        assert result["task_projection"]["revision"] == active["task_projection"]["revision"]

    run(scenario())


def test_host_blocks_misclassified_negated_active_field(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                (
                    "task_input_candidate",
                    {"work_location_description": "二号罐区"},
                    False,
                ),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("host-negative"))
        for request_id, text in (
            ("candidate", "申请"),
            ("confirm", "确认申请"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        before = workflow.calls.copy()
        task_revision = state["task_projection"]["revision"]

        result = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="negated",
            expected_revision=state["revision"],
            text="不要把位置改成二号罐区",
        )

        assert workflow.calls == before
        assert result["task_projection"]["revision"] == task_revision

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


def test_new_task_choice_requires_confirmation_and_switch_checks_owned_task(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                ("switch_or_create_task", {"work_object_description": "V202 补焊"}, True),
                ("confirm_pending_intent",),
                ("confirm_pending_intent",),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(ConversationStore(dsn), CountingFactory(model), workflow)
        state = await subject.create(OWNER, request_id=unique("new-choice"))
        for request_id, text in (
            ("first", "first"),
            ("confirm-first", "确认申请"),
            ("another", "another"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        first_task = state["active_task_id"]
        assert state["pending_intent"]["kind"] == "switch_or_create_task"
        assert len(workflow.tasks) == 1

        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="choose-new",
            expected_revision=state["revision"],
            text="明确新建另一项任务",
        )
        assert state["status"] == "pending_confirmation"
        assert state["active_task_id"] == first_task
        assert state["pending_intent"]["kind"] == "hot_work_candidate"
        assert len(workflow.tasks) == 1

        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="confirm-new",
            expected_revision=state["revision"],
            text="确认申请",
        )
        assert state["active_task_id"] != first_task
        assert first_task in workflow.tasks
        assert len(workflow.tasks) == 2

    run(scenario())


def test_active_hot_candidate_requires_explicit_new_task_choice(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 管线补焊"}, True),
                ("confirm_pending_intent",),
                ("hot_work_candidate", {"work_object_description": "V202 管线补焊"}, True),
                ("confirm_pending_intent",),
                ("reject_pending_intent",),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("active-candidate"))
        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="first",
            expected_revision=state["revision"],
            text="V101 管线补焊",
        )
        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="confirm-first",
            expected_revision=state["revision"],
            text="确认申请",
        )
        first_task = state["active_task_id"]
        calls_before_choice = workflow.calls.copy()

        state = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="candidate-second",
            expected_revision=state["revision"],
            text="另一项 V202 管线补焊",
        )
        assert state["pending_intent"]["kind"] == "switch_or_create_task"
        assert state["active_task_id"] == first_task
        assert workflow.calls == calls_before_choice

        unchanged = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="generic-confirm",
            expected_revision=state["revision"],
            text="确认",
        )
        assert unchanged["pending_intent"]["kind"] == "switch_or_create_task"
        assert unchanged["active_task_id"] == first_task
        assert workflow.calls == calls_before_choice

        rejected = await subject.message(
            OWNER,
            unchanged["conversation_id"],
            request_id="reject-new",
            expected_revision=unchanged["revision"],
            text="我不想新建",
        )
        assert rejected["pending_intent"] is None
        assert rejected["active_task_id"] == first_task
        assert workflow.calls == calls_before_choice

    run(scenario())


def test_host_preserves_switch_choice_when_classifier_misroutes_rejection(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                ("hot_work_candidate", {"work_object_description": "V202 补焊"}, True),
                ("hot_work_candidate", {"work_object_description": "错误覆盖"}, True),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("host-choice"))
        for request_id, text in (
            ("candidate", "申请"),
            ("confirm", "确认申请"),
            ("another", "另一项申请"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        first_task = state["active_task_id"]
        pending = state["pending_intent"]
        before = workflow.calls.copy()

        result = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="misrouted-rejection",
            expected_revision=state["revision"],
            text="我不想新建",
        )

        assert result["pending_intent"] == pending
        assert result["active_task_id"] == first_task
        assert workflow.calls == before

    run(scenario())


def test_switch_can_only_bind_a_task_verified_for_the_current_identity(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                ("switch_task", {}, False, "task-owned"),
                ("switch_task", {}, False, "task-not-owned"),
            ]
        )
        workflow = FakeWorkflow()
        workflow.tasks["task-owned"] = projection("task-owned")
        subject = ConversationService(ConversationStore(dsn), CountingFactory(model), workflow)
        state = await subject.create(OWNER, request_id=unique("switch-owned"))
        for request_id, text in (
            ("candidate", "candidate"),
            ("confirm", "确认申请"),
            ("switch", "切换到 task-owned"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        assert state["active_task_id"] == "task-owned"
        assert state["task_projection"]["task_id"] == "task-owned"

        with pytest.raises(AccessDenied):
            await subject.message(
                OWNER,
                state["conversation_id"],
                request_id="switch-denied",
                expected_revision=state["revision"],
                text="切换到 task-not-owned",
            )
        snapshot = await subject.snapshot(OWNER, state["conversation_id"])
        assert snapshot["active_task_id"] == "task-owned"

    run(scenario())


def test_host_rejects_misclassified_switch_without_matching_explicit_target(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                ("hot_work_candidate", {"work_object_description": "V202 补焊"}, True),
                ("switch_task", {}, False, "task-owned"),
            ]
        )
        workflow = FakeWorkflow()
        workflow.tasks["task-owned"] = projection("task-owned")
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("host-switch-text"))
        for request_id, text in (
            ("candidate", "申请"),
            ("confirm", "确认申请"),
            ("another", "另一项申请"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        original_task = state["active_task_id"]
        pending = state["pending_intent"]

        result = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="misreported-switch",
            expected_revision=state["revision"],
            text="随便聊聊",
        )

        assert result["active_task_id"] == original_task
        assert result["pending_intent"] == pending

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
        for request_id, text in (
            ("candidate", "candidate"),
            ("confirm", "确认申请"),
            ("certain", "certain"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
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


def test_host_requires_explicit_affirmative_for_task_input_pending(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                (
                    "task_input_candidate",
                    {"work_location_description": "可能在二号罐区"},
                    True,
                ),
                ("confirm_pending_intent",),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("host-confirm-input"))
        for request_id, text in (
            ("candidate", "申请"),
            ("confirm", "确认申请"),
            ("ambiguous", "位置可能在二号罐区"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        pending = state["pending_intent"]
        before = workflow.calls.copy()

        result = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="misreported-confirm",
            expected_revision=state["revision"],
            text="解释一下确认流程",
        )

        assert result["pending_intent"] == pending
        assert workflow.calls == before

    run(scenario())


def test_host_preserves_task_input_pending_when_classifier_misroutes_new_task(dsn):  # noqa: F811
    async def scenario():
        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101 补焊"}, True),
                ("confirm_pending_intent",),
                (
                    "task_input_candidate",
                    {"work_location_description": "可能在二号罐区"},
                    True,
                ),
                ("hot_work_candidate", {"work_object_description": "错误新任务"}, True),
            ]
        )
        workflow = FakeWorkflow()
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), workflow
        )
        state = await subject.create(OWNER, request_id=unique("host-input-pending"))
        for request_id, text in (
            ("candidate", "申请"),
            ("confirm", "确认申请"),
            ("ambiguous", "位置可能在二号罐区"),
        ):
            state = await subject.message(
                OWNER,
                state["conversation_id"],
                request_id=request_id,
                expected_revision=state["revision"],
                text=text,
            )
        pending = state["pending_intent"]
        task_id = state["active_task_id"]
        before = workflow.calls.copy()

        result = await subject.message(
            OWNER,
            state["conversation_id"],
            request_id="misreported-new-task",
            expected_revision=state["revision"],
            text="解释一下这个位置",
        )

        assert result["pending_intent"] == pending
        assert result["active_task_id"] == task_id
        assert workflow.calls == before

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


def test_workflow_not_found_replay_preserves_exception_semantics(dsn):  # noqa: F811
    async def scenario():
        class MissingWorkflow(FakeWorkflow):
            async def start(self, *args, **kwargs):
                raise AccessDenied("missing task")

        model = ProposedModel(
            [
                ("hot_work_candidate", {"work_object_description": "V101"}, True),
                ("confirm_pending_intent",),
            ]
        )
        subject = ConversationService(
            ConversationStore(dsn), CountingFactory(model), MissingWorkflow()
        )
        state = await subject.create(OWNER, request_id=unique("workflow-not-found"))
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
        with pytest.raises(AccessDenied):
            await subject.message(**arguments)
        with pytest.raises(AccessDenied):
            await subject.message(**arguments)

    run(scenario())
@pytest.mark.parametrize("failure", [False, True])
def test_business_query_uses_gateway_and_durable_sanitized_failure(dsn, failure):  # noqa: F811
    async def scenario():
        from anlan.business_query.contracts import QueryAnswer

        class Queries:
            calls = []

            async def answer(self, actor, **kwargs):
                self.calls.append((actor, kwargs))
                if failure:
                    raise RuntimeError("PRIVATE-DB-PASSWORD")
                return QueryAnswer(text="申请 task-1 当前为要求补充。", outcome="ok")

        query = Queries()
        subject, workflow, _ = service(dsn)
        subject.business_queries = query
        conv = await subject.create(OWNER, request_id=unique("query"))
        result = await subject.message(OWNER, conv["conversation_id"], request_id="q",
                                       expected_revision=conv["revision"],
                                       text="当前材料状态是什么？")
        assert query.calls[0][1]["source_message_id"]
        snapshot = await subject.snapshot(OWNER, conv["conversation_id"])
        assert workflow.calls == [] and snapshot["active_task_id"] is None
        if failure:
            assert result["error_category"] == "query_failure"
            assert "PRIVATE" not in str(result)
        else:
            assert result["messages"][-1]["text"] == "申请 task-1 当前为要求补充。"
        replay = await subject.message(OWNER, conv["conversation_id"], request_id="q",
                                       expected_revision=conv["revision"],
                                       text="当前材料状态是什么？")
        assert replay == result and len(query.calls) == 1
    run(scenario())

