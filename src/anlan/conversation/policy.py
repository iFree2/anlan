"""Pure deterministic conversation routing; business writes are explicit."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from anlan.business_query.contracts import QueryType
from anlan.common.errors import InvalidTransition
from anlan.common.models import NonEmpty, StrictModel
from anlan.conversation.contracts import (
    BUSINESS_QUERY_INTENTS,
    COLLABORATION_INTENTS,
    ConversationState,
    FrozenCollaborationCommand,
    IntentProposal,
)
from anlan.workflows.material_contracts import FieldName, Text


class RouteAction(StrEnum):
    EXECUTE_BUSINESS_QUERY = "execute_business_query"
    REPLY_ONLY = "reply_only"
    ASK_CONFIRMATION = "ask_confirmation"
    REJECT_PENDING_INTENT = "reject_pending_intent"
    START_HOT_WORK = "start_hot_work"
    ASK_TASK_INPUT_CONFIRMATION = "ask_task_input_confirmation"
    SUBMIT_TASK_INPUT = "submit_task_input"
    PAUSE_TASK = "pause_task"
    RECOVER_TASK = "recover_task"
    DETACH_TASK = "detach_task"
    ASK_TASK_SWITCH = "ask_task_switch"
    PREPARE_NEW_TASK = "prepare_new_task"
    SWITCH_TASK = "switch_task"
    ASK_COLLABORATION_CONFIRMATION = 'ask_collaboration_confirmation'
    EXECUTE_COLLABORATION = 'execute_collaboration'


class RouteDecision(StrictModel):
    action: RouteAction
    query_type: QueryType | None = None
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    active_task_id: NonEmpty | None = None
    business_write: bool = False
    task_revision: int | None = Field(default=None, strict=True, ge=1)
    task_status: Literal["analyzing", "waiting_input", "awaiting_review"] | None = None
    target_task_id: NonEmpty | None = None
    collaboration: FrozenCollaborationCommand | None = None


def decide(state: ConversationState, proposal: IntentProposal) -> RouteDecision:
    """Resolve a bounded proposal against trusted conversation state."""
    intent = proposal.intent

    if intent in BUSINESS_QUERY_INTENTS:
        return RouteDecision(action=RouteAction.EXECUTE_BUSINESS_QUERY,
                             active_task_id=state.active_task_id,
                             target_task_id=proposal.target_task_id,
                             query_type=BUSINESS_QUERY_INTENTS[intent], business_write=False)

    if intent in COLLABORATION_INTENTS:
        if not state.active_task_id or state.status not in {
            'active_hot_work', 'pending_confirmation'}:
            raise InvalidTransition('请先选择有权访问的申请')
        return _decision(RouteAction.ASK_COLLABORATION_CONFIRMATION, state)

    if intent == "casual_chat":
        return _decision(RouteAction.REPLY_ONLY, state)

    if intent == "hot_work_candidate":
        if state.status == "active_hot_work":
            return _decision(RouteAction.ASK_TASK_SWITCH, state, proposal.fields)
        if state.status in {"idle", "pending_confirmation"}:
            return _decision(RouteAction.ASK_CONFIRMATION, state, proposal.fields)
        raise InvalidTransition("暂停任务期间不能静默创建另一项任务")

    if intent == "switch_or_create_task":
        if state.status == "active_hot_work":
            return _decision(RouteAction.ASK_TASK_SWITCH, state, proposal.fields)
        if state.status == "idle":
            return _decision(RouteAction.ASK_CONFIRMATION, state, proposal.fields)
        raise InvalidTransition("当前会话状态不能切换或新建任务")

    if intent == "switch_task":
        if (
            state.status not in {"active_hot_work", "pending_confirmation"}
            or not state.active_task_id
        ):
            raise InvalidTransition("当前没有可切换的活动任务")
        if not proposal.target_task_id:
            raise InvalidTransition("切换任务需要明确的任务标识")
        return RouteDecision(
            action=RouteAction.SWITCH_TASK,
            active_task_id=state.active_task_id,
            target_task_id=proposal.target_task_id,
        )

    if intent == "confirm_pending_intent":
        pending = state.pending_intent
        if state.status != "pending_confirmation" or pending is None:
            raise InvalidTransition("没有可确认的待处理意图")
        if pending.kind in COLLABORATION_INTENTS:
            if not pending.collaboration or pending.collaboration.task_id != state.active_task_id:
                raise InvalidTransition('协作卡片与当前申请不一致')
            return RouteDecision(action=RouteAction.EXECUTE_COLLABORATION,
                                 active_task_id=state.active_task_id, business_write=True,
                                 collaboration=pending.collaboration)
        if pending.kind == "hot_work_candidate":
            return _decision(RouteAction.START_HOT_WORK, state, pending.fields, write=True)
        if pending.kind == "task_input_candidate" and state.active_task_id:
            return _decision(RouteAction.SUBMIT_TASK_INPUT, state, pending.fields, write=True)
        if pending.kind == "switch_or_create_task" and state.active_task_id:
            return _decision(RouteAction.PREPARE_NEW_TASK, state, pending.fields)
        raise InvalidTransition("待处理意图不能在当前状态确认")

    if intent == "reject_pending_intent":
        if state.status != "pending_confirmation" or state.pending_intent is None:
            raise InvalidTransition("没有可拒绝的待处理意图")
        return _decision(RouteAction.REJECT_PENDING_INTENT, state)

    if intent == "task_input_candidate":
        if state.status != "active_hot_work" or not state.active_task_id:
            raise InvalidTransition("当前没有可补充的活动任务")
        action = (
            RouteAction.ASK_TASK_INPUT_CONFIRMATION
            if proposal.requires_confirmation
            else RouteAction.SUBMIT_TASK_INPUT
        )
        return _decision(
            action,
            state,
            proposal.fields,
            write=action is RouteAction.SUBMIT_TASK_INPUT,
        )

    if intent == "pause_task":
        if state.status != "active_hot_work" or not state.active_task_id:
            raise InvalidTransition("当前没有可暂停的活动任务")
        return _decision(RouteAction.PAUSE_TASK, state)

    if intent == "resume_task":
        if state.status != "paused" or not state.active_task_id:
            raise InvalidTransition("当前没有可恢复的暂停任务")
        return _decision(RouteAction.RECOVER_TASK, state, write=True)

    if intent == "cancel_task":
        if state.status not in {"active_hot_work", "paused"} or not state.active_task_id:
            raise InvalidTransition("当前没有可取消引导的任务")
        return _decision(RouteAction.DETACH_TASK, state)

    raise InvalidTransition("不支持的会话状态迁移")


def _decision(
    action: RouteAction,
    state: ConversationState,
    fields: dict[FieldName, Text] | None = None,
    *,
    write: bool = False,
) -> RouteDecision:
    if write and action not in {
        RouteAction.START_HOT_WORK,
        RouteAction.SUBMIT_TASK_INPUT,
        RouteAction.RECOVER_TASK,
    }:
        raise InvalidTransition("该路由动作无权产生业务写入")
    return RouteDecision(
        action=action,
        fields=fields or {},
        active_task_id=state.active_task_id,
        business_write=write,
    )
