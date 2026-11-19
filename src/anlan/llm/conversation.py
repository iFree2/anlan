"""Bounded, tool-free conversation classifier and chat responder adapters."""

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from anlan.common.models import NonEmpty, StrictModel
from anlan.conversation.contracts import (
    CollaborationInput,
    ConversationStatus,
    IntentKind,
    IntentProposal,
    PendingIntent,
    QueryWriteCandidate,
)
from anlan.infrastructure.budget import CONVERSATION_WORK_PACKAGE
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.gateway import ModelGateway
from anlan.workflows.material_contracts import FieldName, Text

INTENT_PROMPT_VERSION = "conversation-intent-v2"
CHAT_PROMPT_VERSION = "conversation-chat-v2"
_MAX_CONTEXT_BYTES = 16 * 1024
_MAX_VISIBLE_MESSAGES = 12


class VisibleMessage(StrictModel):
    role: Literal["user", "assistant", "system_event"]
    text: str = Field(strict=True, min_length=1, max_length=8192)


class ConversationContext(StrictModel):
    status: ConversationStatus
    messages: list[VisibleMessage] = Field(default_factory=list, max_length=100)
    pending_intent: PendingIntent | None = None
    task_projection: dict | None = None
    collaboration_role: Literal['applicant', 'safety_manager'] | None = None


class AssistantReply(StrictModel):
    text: NonEmpty


class _ProviderIntentProposal(StrictModel):
    intent: IntentKind
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    requires_confirmation: bool = False
    target_task_id: NonEmpty | None = None
    user_explanation: NonEmpty
    classifier_version: str | None = None
    collaboration: CollaborationInput | None = None
    query_write: QueryWriteCandidate | None = None


class IntentClassifier(Protocol):
    async def classify(
        self, context: ConversationContext, *, run_id: str = "conversation-classify"
    ) -> IntentProposal: ...


class ChatResponder(Protocol):
    async def respond(
        self, context: ConversationContext, *, run_id: str = "conversation-chat"
    ) -> AssistantReply: ...


@dataclass(frozen=True)
class ConversationModelPair:
    classifier: IntentClassifier
    responder: ChatResponder


def _safe_task_projection(value: dict | None) -> dict | None:
    if value is None:
        return None
    allowed = {
        "task_id",
        "status",
        "revision",
        "fields",
        "missing_fields",
        "issue_questions",
        "analysis_mode",
        "semantic_status",
        "recoverable",
        "event_count",
        "review_count",
        "stale_review_warning",
        'collaboration',
        'collaboration_role',
    }
    result = {key: value[key] for key in allowed if key in value}
    if isinstance(result.get('collaboration'), dict):
        shared = result['collaboration']
        app_keys = {'task_id', 'status', 'version', 'applicant_user_id', 'reviewer_user_id',
                    'submitted_material_revision', 'completed_material_revision'}
        event_keys = {'event_id', 'task_id', 'actor_user_id', 'actor_role', 'action',
                      'material_revision', 'application_version'}
        payload_keys = {'reviewer_user_id', 'questions', 'reply', 'conclusion',
                        'receipt_id', 'review_id', 'decision'}
        result['collaboration'] = {
            'application': {k: v for k, v in shared.get('application', {}).items()
                            if k in app_keys},
            'allowed_actions': shared.get('allowed_actions', []),
            'events': [{k: v for k, v in event.items() if k in event_keys} | {
                'payload': {k: v for k, v in event.get('payload', {}).items() if k in payload_keys}}
                for event in shared.get('events', [])[-20:]],
        }
    return result


def serialize_context(context: ConversationContext) -> str:
    """Serialize only bounded visible context, trimming oldest/longest text first."""
    value = {
        "status": context.status,
        'collaboration_role': context.collaboration_role,
        "messages": [message.model_dump() for message in context.messages[-_MAX_VISIBLE_MESSAGES:]],
        "pending_intent": (
            context.pending_intent.model_dump(mode="json") if context.pending_intent else None
        ),
        "task_projection": _safe_task_projection(context.task_projection),
    }
    while True:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode()) <= _MAX_CONTEXT_BYTES:
            return serialized
        if len(value["messages"]) > 1:
            value["messages"].pop(0)
            continue
        if value["messages"] and len(value["messages"][0]["text"]) > 1:
            text = value["messages"][0]["text"]
            value["messages"][0]["text"] = text[len(text) // 2 :]
            continue
        if value["task_projection"] is not None:
            value["task_projection"] = None
            continue
        pending = value["pending_intent"]
        if isinstance(pending, dict) and pending.get('collaboration'):
            # Provider context can omit a large card; the persisted command is never trimmed.
            pending['collaboration'] = None
            continue
        fields = pending.get("fields", {}) if isinstance(pending, dict) else {}
        candidates = [(len(text.encode()), name, text) for name, text in fields.items()]
        if candidates:
            _, name, text = max(candidates)
            if len(text) > 1:
                fields[name] = text[: max(1, len(text) // 2)]
                continue
            fields.pop(name)
            continue
        raise ValueError("Conversation context cannot fit the provider boundary")


def _parse_message(envelope: dict) -> str:
    choice = envelope["choices"][0]
    message = choice["message"]
    if (
        choice["finish_reason"] != "stop"
        or message["role"] != "assistant"
        or message.get("tool_calls")
        or not isinstance(message["content"], str)
    ):
        raise ValueError("Expected one final JSON response")
    return message["content"]


class DeepSeekIntentClassifier:
    mode = "deepseek_live"

    def __init__(self, config, client, ledger):
        self.gateway = ModelGateway(
            config, client, ledger, work_package=CONVERSATION_WORK_PACKAGE
        )

    async def classify(
        self, context: ConversationContext, *, run_id: str = "conversation-classify"
    ) -> IntentProposal:
        def parse(envelope):
            try:
                candidate = _ProviderIntentProposal.model_validate_json(_parse_message(envelope))
            except (ValidationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise ValueError("Invalid intent proposal") from None
            return IntentProposal(
                intent=candidate.intent,
                fields=candidate.fields,
                requires_confirmation=candidate.requires_confirmation,
                target_task_id=candidate.target_task_id,
                user_explanation=candidate.user_explanation,
                classifier_version=INTENT_PROMPT_VERSION,
                collaboration=candidate.collaboration,
                query_write=candidate.query_write,
            )

        try:
            proposal, _, _ = await self.gateway.call(
                {
                    "model": self.gateway.config.model,
                    "thinking": {"type": "disabled"},
                    "temperature": 0,
                    "max_tokens": 1024,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是受限意图分类器，只返回一个 JSON 对象，不得执行工具、"
                                "业务写入或输出隐藏推理。JSON schema："
                                '{"intent":"下列枚举之一","fields":{"字段名":"字符串"},'
                                '"requires_confirmation":false,"target_task_id":null,'
                                '"user_explanation":"简短说明"}。intent 枚举：casual_chat、'
                                "hot_work_candidate、confirm_pending_intent、"
                                "reject_pending_intent、task_input_candidate、pause_task、"
                                "resume_task、cancel_task、switch_or_create_task、switch_task、"
                                "submit_application、request_changes、resubmit_application、"
                                "complete_material_review。协作候选另用 collaboration 对象："
                                "状态、详情、流程和安全知识问题分别使用 query_application_status、"
                                "query_application_details、query_process_guidance、"
                                "query_safety_knowledge；查询只读，不携带 fields，不得编造证据、"
                                "身份、版本或声称已修改。target_task_id 仅可来自用户原文同一标识。"
                                "混合查询与明确写请求时以 query_* 为主，另用可空 query_write："
                                "{intent,fields,collaboration} 表示独立待确认候选。"
                                "query_write 不能携带身份、版本、request_id或采纳引用；"
                                "宿主校验并冻结。"
                                "submit_application 只带 reviewer_user_id；request_changes 只带"
                                "questions 字符串数组；resubmit_application 只带 reply；"
                                "complete_material_review 只带 conclusion。"
                                "每个说明非空且至多500字，"
                                "questions至多20条。不输出版本、request_id或身份；宿主冻结。"
                                "依 collaboration_role 和 "
                                "task_projection.collaboration.allowed_actions"
                                "提议，安全人员不得创建或修改材料；提交申请与补充材料是不同动作。"
                                "fields 只允许 work_location_description、"
                                "work_object_description、work_method_description、"
                                "attachment_description；不得加入其他字段。switch_task 仅在用户"
                                "明确说切换到某任务时设置 target_task_id，宿主仍会校验归属。"
                                "当待处理意图是 switch_or_create_task 时，只有用户明确选择新建"
                                "才返回 confirm_pending_intent；单独说确认不得推进。"
                                "否定、尚未确认、疑问、引用他人话语、假设和知识咨询不得分类为确认"
                                "或材料写入；确认必须是针对当前候选的整句明确肯定。活动任务中的"
                                "明确字段补充才是 task_input_candidate，普通焊接知识问题仍是"
                                "casual_chat。classifier_version 由宿主最终写入，响应中无需提供。"
                            ),
                        },
                        {"role": "user", "content": serialize_context(context)},
                    ],
                },
                parse,
                run_id,
            )
        except AnalysisFailure:
            raise
        return proposal


class DeepSeekChatResponder:
    mode = "deepseek_live"

    def __init__(self, config, client, ledger):
        self.gateway = ModelGateway(
            config, client, ledger, work_package=CONVERSATION_WORK_PACKAGE
        )

    async def respond(
        self, context: ConversationContext, *, run_id: str = "conversation-chat"
    ) -> AssistantReply:
        def parse(envelope):
            try:
                return AssistantReply.model_validate_json(_parse_message(envelope))
            except (ValidationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise ValueError("Invalid chat response") from None

        reply, _, _ = await self.gateway.call(
            {
                "model": self.gateway.config.model,
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "max_tokens": 1024,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"你是安澜的受限闲聊响应器（{CHAT_PROMPT_VERSION}）。"
                            "只返回 JSON 对象，格式为"
                            '{"text":"..."}。不得声称任务已创建、更新、批准或恢复；'
                            "不得执行工具或业务写入，任务状态仅以服务端侧栏为准。"
                        ),
                    },
                    {"role": "user", "content": serialize_context(context)},
                ],
            },
            parse,
            run_id,
        )
        return reply


class ScriptedConversationModel:
    """Deterministic protocol double; it is not model-quality evidence."""

    mode = "scripted_double"

    async def classify(
        self, context: ConversationContext, *, run_id: str = "conversation-classify"
    ) -> IntentProposal:
        del run_id
        text = context.messages[-1].text.strip() if context.messages else ""
        target_task_id = None
        collaboration = None
        normalized = text.rstrip("。！! ")
        negative = any(
            phrase in text
            for phrase in (
                "不确认",
                "不要确认",
                "还没确认",
                "尚未确认",
                "不是申请",
                "并非申请",
                "不要申请",
                "不要把",
                "别把",
                "不想新建",
                "不要新建",
            )
        )
        question = any(mark in text for mark in ("?", "？")) or any(
            word in text for word in ("什么", "为什么", "怎么", "如何", "区别", "解释", "流程")
        )
        if query_intent := _scripted_query_intent(text):
            intent, fields, confirmation = query_intent, {}, False
            match = re.search(r"(?:申请|任务)\s+([A-Za-z0-9._:-]{1,100})", text)
            target_task_id = match.group(1) if match else None
        elif (
            context.pending_intent
            and context.pending_intent.kind == "switch_or_create_task"
            and "新建" in text
            and not negative
        ):
            intent = "confirm_pending_intent"
            fields = {}
            confirmation = False
        elif (
            context.pending_intent
            and context.pending_intent.kind != "switch_or_create_task"
            and normalized in {
            "确认", "确认申请", "同意", "是的", "确认继续"
            }
        ):
            intent = "confirm_pending_intent"
            fields = {}
            confirmation = False
        elif context.pending_intent and any(
            word in text
            for word in (
                "不是",
                "取消",
                "取消申请",
                "否认",
                "不确认",
                "不要确认",
                "不想新建",
                "不要新建",
            )
        ):
            intent = "reject_pending_intent"
            fields = {}
            confirmation = False
        elif not negative and not question and (match := re.fullmatch(
            r'提交申请给\s+([A-Za-z0-9._:-]{1,100})', normalized)):
            intent, fields, confirmation = 'submit_application', {}, True
            collaboration = CollaborationInput(reviewer_user_id=match.group(1))
        elif not negative and not question and (match := re.fullmatch(
            r'(要求补充|重新提交申请|完成材料核查)[：:]\s*(.+)', normalized)):
            intent, fields, confirmation = {
                '要求补充': 'request_changes', '重新提交申请': 'resubmit_application',
                '完成材料核查': 'complete_material_review',
            }[match.group(1)], {}, True
            collaboration = CollaborationInput.model_validate({
                {'要求补充': 'questions', '重新提交申请': 'reply',
                 '完成材料核查': 'conclusion'}[match.group(1)]:
                [match.group(2)] if match.group(1) == '要求补充' else match.group(2)})
        elif context.status in {"active_hot_work", "pending_confirmation"} and (
            switch_match := re.fullmatch(
                r"切换到\s*([A-Za-z0-9._:-]{1,100})", normalized
            )
        ):
            intent, fields, confirmation = "switch_task", {}, False
            target_task_id = switch_match.group(1)
        elif (
            context.status == "active_hot_work"
            and any(word in text for word in ("取消当前任务", "取消引导", "结束引导"))
        ):
            intent, fields, confirmation = "cancel_task", {}, False
        elif (
            any(word in text for word in ("暂停", "等一下"))
            and context.status == "active_hot_work"
        ):
            intent, fields, confirmation = "pause_task", {}, False
        elif any(word in text for word in ("恢复", "继续任务")) and context.status == "paused":
            intent, fields, confirmation = "resume_task", {}, False
        elif context.status == "active_hot_work" and not question and not negative:
            extracted = _scripted_material_fields(text)
            if any(word in text for word in ("另一个任务", "另一项", "重新申请", "新任务")):
                intent, fields, confirmation = "switch_or_create_task", extracted, True
            elif extracted:
                intent, fields, confirmation = "task_input_candidate", extracted, False
            else:
                intent, fields, confirmation = "casual_chat", {}, False
        elif (
            any(word in text for word in ("动火", "补焊", "焊接", "切割"))
            and not negative
            and not question
            and not any(word in text for word in ("只是讨论", "举例", "假如", "如果", "引用"))
        ):
            intent = "hot_work_candidate"
            fields = _scripted_material_fields(text) or {"work_object_description": text}
            confirmation = True
        else:
            intent, fields, confirmation = "casual_chat", {}, False
        return IntentProposal(
            intent=intent,
            fields=fields,
            requires_confirmation=confirmation,
            target_task_id=target_task_id,
            user_explanation="SYNTHETIC 规则替身的有界分类",
            classifier_version="scripted-intent-v1",
            collaboration=collaboration,
            query_write=_scripted_query_write(text) if intent.startswith("query_") else None,
        )

    async def respond(
        self, context: ConversationContext, *, run_id: str = "conversation-chat"
    ) -> AssistantReply:
        del context, run_id
        return AssistantReply(text="SYNTHETIC：我可以继续对话；业务任务状态以侧栏为准。")


def _unsafe_write_text(text: str) -> bool:
    return any(word in text for word in (
        "?", "？", "吗", "什么", "为什么", "怎么", "如何", "解释", "流程", "区别",
        "不要", "别", "不想", "不用", "无需", "并非", "不是", "不确认", "还没", "尚未",
        "请勿", "不执行", "不修改", "暂不", "假如", "如果", "假设", "举例",
        "引用", "他说", "忽略", "ignore", "越过", "绕过", "“", "”", '"', "‘", "’",
    ))


def _scripted_query_write(text: str) -> QueryWriteCandidate | None:
    """Only explicit separate imperative clauses may propose a confirmed follow-up."""
    if any(marker in text.lower() for marker in (
        "假如", "如果", "假设", "引用", "他说", "忽略", "越过", "绕过", "ignore",
        "不要", "别", "不想", "不用", "无需", "并非", "不是", "不执行", "不修改", "不做",
        "暂不", "请勿", "还没", "尚未", "不确认", "“", "”", '"', "‘", "’",
    )):
        return None
    for clause in re.split(r"[。；;？?!！]", text):
        clause = re.sub(r"^(?:另外|然后|请|再|同时)[，,\s]*", "", clause.strip())
        if not clause or _unsafe_write_text(clause):
            continue
        match = re.fullmatch(r"把((?:作业)?位置|(?:作业)?对象|(?:作业)?方式|附件说明)"
                             r"(?:改成|改为|修改为)([^，,]+)", clause)
        if match:
            name = {"位置": "work_location_description", "对象": "work_object_description",
                    "方式": "work_method_description", "附件说明": "attachment_description"}[
                        match.group(1).removeprefix("作业")]
            return QueryWriteCandidate(intent="task_input_candidate", fields={name: match.group(2)})
        match = re.fullmatch(r"提交申请给\s+([A-Za-z0-9._:-]{1,100})", clause)
        if match:
            return QueryWriteCandidate(intent="submit_application",
                                       collaboration=CollaborationInput(
                                           reviewer_user_id=match.group(1)))
        match = re.fullmatch(r"(要求补充|重新提交申请|完成材料核查)[：:]\s*(.+)", clause)
        if match:
            intent, field = {"要求补充": ("request_changes", "questions"),
                             "重新提交申请": ("resubmit_application", "reply"),
                             "完成材料核查": ("complete_material_review", "conclusion")
                             }[match.group(1)]
            value = [match.group(2)] if field == "questions" else match.group(2)
            return QueryWriteCandidate(
                intent=intent, collaboration=CollaborationInput.model_validate({field: value}))
    return None


def _scripted_query_intent(text: str) -> str | None:
    if any(p in text for p in ("材料状态", "申请状态", "当前状态", "当前进度", "轮到谁")):
        return "query_application_status"
    if any(p in text for p in ("缺哪些", "作业对象是什么", "作业位置是什么",
                               "作业方式是什么", "附件是什么")):
        return "query_application_details"
    if any(p in text for p in ("下一步", "为什么不能", "不能重新提交", "怎么提交",
                               "如何重新提交", "为什么现在不能")):
        return "query_process_guidance"
    if any(p in text for p in ("？", "?", "为什么", "区别", "如何")) and any(
        p in text for p in ("动火", "气体检测", "防护", "焊", "切割", "开工", "工艺")
    ):
        return "query_safety_knowledge"
    return None


def _scripted_material_fields(text: str) -> dict[FieldName, Text]:
    """Small deterministic demo grammar; never evidence of model quality."""
    patterns = {
        "work_location_description": r"(?:作业)?位置(?:在|是|为)?\s*([^，。；;!?？]+)",
        "work_object_description": r"(?:作业)?对象(?:是|为)?\s*([^，。；;!?？]+)",
        "work_method_description": r"(?:作业)?方式(?:是|为)?\s*([^，。；;!?？]+)",
        "attachment_description": r"附件(?:说明)?(?:是|为)?\s*([^，。；;!?？]+)",
    }
    result = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match and match.group(1).strip():
            result[name] = match.group(1).strip()
    return result
