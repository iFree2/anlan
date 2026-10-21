"""Bounded, tool-free conversation classifier and chat responder adapters."""

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from anlan.common.models import NonEmpty, StrictModel
from anlan.conversation.contracts import (
    ConversationStatus,
    IntentKind,
    IntentProposal,
    PendingIntent,
)
from anlan.infrastructure.budget import CONVERSATION_WORK_PACKAGE
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.gateway import ModelGateway
from anlan.workflows.material_contracts import FieldName, Text

INTENT_PROMPT_VERSION = "conversation-intent-v2"
CHAT_PROMPT_VERSION = "conversation-chat-v1"
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


class AssistantReply(StrictModel):
    text: NonEmpty


class _ProviderIntentProposal(StrictModel):
    intent: IntentKind
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    requires_confirmation: bool = False
    target_task_id: NonEmpty | None = None
    user_explanation: NonEmpty
    classifier_version: str | None = None


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
    }
    return {key: value[key] for key in allowed if key in value}


def serialize_context(context: ConversationContext) -> str:
    """Serialize only bounded visible context, trimming oldest/longest text first."""
    value = {
        "status": context.status,
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
                                "resume_task、cancel_task、switch_or_create_task、switch_task。"
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
                            f"你是安澜的受限闲聊响应器（{CHAT_PROMPT_VERSION}）。只返回"
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
        if (
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
        )

    async def respond(
        self, context: ConversationContext, *, run_id: str = "conversation-chat"
    ) -> AssistantReply:
        del context, run_id
        return AssistantReply(text="SYNTHETIC：我可以继续对话；业务任务状态以侧栏为准。")


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
