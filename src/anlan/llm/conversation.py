"""Bounded, tool-free conversation classifier and chat responder adapters."""

import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from anlan.common.models import NonEmpty, StrictModel
from anlan.conversation.contracts import ConversationStatus, IntentProposal, PendingIntent
from anlan.infrastructure.budget import CONVERSATION_WORK_PACKAGE
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.gateway import ModelGateway

INTENT_PROMPT_VERSION = "conversation-intent-v1"
CHAT_PROMPT_VERSION = "conversation-chat-v1"
_MAX_CONTEXT_BYTES = 16 * 1024
_MAX_VISIBLE_MESSAGES = 12


class VisibleMessage(StrictModel):
    role: Literal["user", "assistant", "system_event"]
    text: str = Field(strict=True, min_length=1, max_length=8000)


class ConversationContext(StrictModel):
    status: ConversationStatus
    messages: list[VisibleMessage] = Field(default_factory=list, max_length=100)
    pending_intent: PendingIntent | None = None
    task_projection: dict | None = None


class AssistantReply(StrictModel):
    text: NonEmpty


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
                proposal = IntentProposal.model_validate_json(_parse_message(envelope))
            except (ValidationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise ValueError("Invalid intent proposal") from None
            return proposal.model_copy(update={"classifier_version": INTENT_PROMPT_VERSION})

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
                                "你是受限意图分类器。只返回一个符合 IntentProposal 的 JSON 对象；"
                                "不得执行工具、业务写入或输出隐藏推理。"
                                "classifier_version 可留空占位。"
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
        if context.pending_intent and any(word in text for word in ("确认", "同意", "是的")):
            intent = "confirm_pending_intent"
            fields = {}
            confirmation = False
        elif context.pending_intent and any(word in text for word in ("不是", "取消", "否认")):
            intent = "reject_pending_intent"
            fields = {}
            confirmation = False
        elif (
            any(word in text for word in ("暂停", "等一下"))
            and context.status == "active_hot_work"
        ):
            intent, fields, confirmation = "pause_task", {}, False
        elif any(word in text for word in ("恢复", "继续任务")) and context.status == "paused":
            intent, fields, confirmation = "resume_task", {}, False
        elif any(word in text for word in ("动火", "补焊", "焊接", "切割")):
            intent = "hot_work_candidate"
            fields = {"work_object_description": text}
            confirmation = True
        else:
            intent, fields, confirmation = "casual_chat", {}, False
        return IntentProposal(
            intent=intent,
            fields=fields,
            requires_confirmation=confirmation,
            user_explanation="SYNTHETIC 规则替身的有界分类",
            classifier_version="scripted-intent-v1",
        )

    async def respond(
        self, context: ConversationContext, *, run_id: str = "conversation-chat"
    ) -> AssistantReply:
        del context, run_id
        return AssistantReply(text="SYNTHETIC：我可以继续对话；业务任务状态以侧栏为准。")
