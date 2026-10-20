import pytest

from anlan.common.errors import InvalidTransition
from anlan.conversation.contracts import ConversationState, IntentProposal
from anlan.conversation.policy import RouteAction, decide


def proposal(intent, *, fields=None, requires_confirmation=False):
    return IntentProposal(
        intent=intent,
        fields=fields or {},
        requires_confirmation=requires_confirmation,
        user_explanation="bounded explanation",
        classifier_version="scripted-intent-v1",
    )


def test_hot_work_candidate_never_starts_without_confirmation():
    state = ConversationState(conversation_id="conv-1", revision=1)
    route = decide(
        state,
        proposal(
            "hot_work_candidate",
            fields={"work_object_description": "V101 管线补焊"},
            requires_confirmation=True,
        ),
    )
    assert route.action == RouteAction.ASK_CONFIRMATION
    assert route.business_write is False


def test_confirmation_starts_only_the_saved_pending_intent():
    state = ConversationState.model_validate(
        {
            "conversation_id": "conv-1",
            "revision": 2,
            "status": "pending_confirmation",
            "pending_intent": {
                "intent_id": "intent-1",
                "kind": "hot_work_candidate",
                "fields": {"work_object_description": "V101 管线补焊"},
                "revision": 1,
            },
        }
    )
    route = decide(state, proposal("confirm_pending_intent"))
    assert route.action == RouteAction.START_HOT_WORK
    assert route.fields == {"work_object_description": "V101 管线补焊"}
    assert route.business_write is True


def test_casual_chat_during_active_task_preserves_binding():
    state = ConversationState(
        conversation_id="conv-1",
        revision=3,
        status="active_hot_work",
        active_task_id="task-1",
    )
    route = decide(state, proposal("casual_chat"))
    assert route.action == RouteAction.REPLY_ONLY
    assert route.active_task_id == "task-1"
    assert route.business_write is False


def test_rejection_discards_the_pending_candidate_without_a_business_write():
    state = pending_state()
    route = decide(state, proposal("reject_pending_intent"))
    assert route.action == RouteAction.REJECT_PENDING_INTENT
    assert route.business_write is False


def test_new_candidate_amends_the_pending_candidate_and_requires_confirmation_again():
    state = pending_state()
    route = decide(
        state,
        proposal(
            "hot_work_candidate",
            fields={"work_location_description": "二号罐区"},
            requires_confirmation=True,
        ),
    )
    assert route.action == RouteAction.ASK_CONFIRMATION
    assert route.fields == {"work_location_description": "二号罐区"}
    assert route.business_write is False


def test_pause_and_resume_are_explicit_and_only_resume_can_recover_the_task():
    active = ConversationState(
        conversation_id="conv-1",
        revision=3,
        status="active_hot_work",
        active_task_id="task-1",
    )
    paused = active.model_copy(update={"revision": 4, "status": "paused"})

    pause = decide(active, proposal("pause_task"))
    resume = decide(paused, proposal("resume_task"))

    assert pause.action == RouteAction.PAUSE_TASK
    assert pause.active_task_id == "task-1"
    assert pause.business_write is False
    assert resume.action == RouteAction.RECOVER_TASK
    assert resume.active_task_id == "task-1"
    assert resume.business_write is True


def test_cancel_detaches_conversation_without_a_business_write():
    state = ConversationState(
        conversation_id="conv-1",
        revision=3,
        status="active_hot_work",
        active_task_id="task-1",
    )
    route = decide(state, proposal("cancel_task"))
    assert route.action == RouteAction.DETACH_TASK
    assert route.active_task_id == "task-1"
    assert route.business_write is False


def test_ambiguous_task_input_asks_before_writing():
    state = ConversationState(
        conversation_id="conv-1",
        revision=3,
        status="active_hot_work",
        active_task_id="task-1",
    )
    fields = {"work_location_description": "可能是二号罐区"}
    route = decide(
        state,
        proposal("task_input_candidate", fields=fields, requires_confirmation=True),
    )
    assert route.action == RouteAction.ASK_TASK_INPUT_CONFIRMATION
    assert route.fields == fields
    assert route.business_write is False


def test_unambiguous_task_input_is_the_only_input_path_that_writes():
    state = ConversationState(
        conversation_id="conv-1",
        revision=3,
        status="active_hot_work",
        active_task_id="task-1",
    )
    route = decide(
        state,
        proposal(
            "task_input_candidate",
            fields={"work_location_description": "二号罐区东侧"},
        ),
    )
    assert route.action == RouteAction.SUBMIT_TASK_INPUT
    assert route.business_write is True


@pytest.mark.parametrize("intent", ["hot_work_candidate", "switch_or_create_task"])
def test_new_request_during_active_task_requires_switch_choice(intent):
    state = ConversationState(
        conversation_id="conv-1",
        revision=3,
        status="active_hot_work",
        active_task_id="task-1",
    )
    route = decide(
        state,
        proposal(
            intent,
            fields={"work_object_description": "V202 管线补焊"},
            requires_confirmation=True,
        ),
    )
    assert route.action == RouteAction.ASK_TASK_SWITCH
    assert route.active_task_id == "task-1"
    assert route.business_write is False


@pytest.mark.parametrize(
    ("state", "intent"),
    [
        (ConversationState(conversation_id="conv-1", revision=1), "confirm_pending_intent"),
        (ConversationState(conversation_id="conv-1", revision=1), "resume_task"),
        (ConversationState(conversation_id="conv-1", revision=1), "task_input_candidate"),
    ],
)
def test_impossible_state_and_intent_combinations_are_rejected(state, intent):
    with pytest.raises(InvalidTransition):
        decide(state, proposal(intent))


def pending_state():
    return ConversationState.model_validate(
        {
            "conversation_id": "conv-1",
            "revision": 2,
            "status": "pending_confirmation",
            "pending_intent": {
                "intent_id": "intent-1",
                "kind": "hot_work_candidate",
                "fields": {"work_object_description": "V101 管线补焊"},
                "revision": 1,
            },
        }
    )
