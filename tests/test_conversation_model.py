import json

import httpx
import pytest

from anlan.conversation.contracts import PendingIntent
from anlan.interfaces.service_config import ServiceConfig
from anlan.interfaces.service_models import ServiceModels
from anlan.llm.config import ModelConfig
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.conversation import (
    ConversationContext,
    DeepSeekChatResponder,
    DeepSeekIntentClassifier,
    ScriptedConversationModel,
    VisibleMessage,
)


class FakeLedger:
    def __init__(self):
        self.reserved = []
        self.finished = []

    async def reserve(self, work_package, run_id):
        self.reserved.append((work_package, run_id))
        return f"attempt-{len(self.reserved)}"

    async def finish(self, attempt, status, usage=None, error=None):
        self.finished.append((attempt, status, usage, error))


def context(text, *, pending=False, messages=None, task_projection=None):
    history = messages or [VisibleMessage(role="user", text=text)]
    candidate = None
    status = "idle"
    if pending:
        status = "pending_confirmation"
        candidate = PendingIntent(
            intent_id="intent-1",
            kind="hot_work_candidate",
            fields={"work_object_description": "V101 管线补焊"},
            revision=1,
        )
    return ConversationContext(
        status=status,
        messages=history,
        pending_intent=candidate,
        task_projection=task_projection,
    )


def model_response(value):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(value, ensure_ascii=False),
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


@pytest.mark.asyncio
async def test_scripted_classifier_separates_chat_candidate_and_confirmation():
    model = ScriptedConversationModel()
    assert (await model.classify(context("今天天气怎么样"))).intent == "casual_chat"
    candidate = await model.classify(context("明天在 V101 管线上补焊"))
    assert candidate.intent == "hot_work_candidate"
    assert candidate.fields == {"work_object_description": "明天在 V101 管线上补焊"}
    assert candidate.requires_confirmation is True
    assert (await model.classify(context("确认申请", pending=True))).intent == (
        "confirm_pending_intent"
    )
    assert "SYNTHETIC" in (await model.respond(context("你好"))).text


@pytest.mark.asyncio
async def test_live_classifier_rejects_unknown_intent_and_never_sends_identity():
    requests = []

    async def handler(request):
        requests.append(request)
        return model_response(
            {
                "intent": "invented_tool_call",
                "fields": {},
                "requires_confirmation": False,
                "user_explanation": "x",
                "classifier_version": "ignored",
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekIntentClassifier(
            ModelConfig(api_key="secret-sentinel"), client, FakeLedger()
        )
        with pytest.raises(AnalysisFailure) as error:
            await model.classify(context("hello"), run_id="message-1")

    assert error.value.category == "invalid_output"
    assert len(requests) == 1
    request = json.loads(requests[0].content)
    serialized = json.dumps(request, ensure_ascii=False)
    assert "tenant_id" not in serialized and "user_id" not in serialized
    assert "secret-sentinel" not in serialized
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 1024
    assert "tools" not in request


@pytest.mark.asyncio
async def test_context_is_bounded_to_twelve_visible_messages_and_sixteen_kib():
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return model_response(
            {
                "intent": "casual_chat",
                "fields": {},
                "requires_confirmation": False,
                "user_explanation": "普通对话",
                "classifier_version": "provider-value-must-be-ignored",
            }
        )

    messages = [
        VisibleMessage(role="user", text=f"旧消息-{index}-" + "字" * 1200)
        for index in range(20)
    ]
    bounded = context("unused", messages=messages, task_projection={"status": "waiting_input"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        proposal = await DeepSeekIntentClassifier(
            ModelConfig(api_key="test"), client, FakeLedger()
        ).classify(bounded, run_id="message-bounded")

    assert proposal.classifier_version == "conversation-intent-v1"
    prompt_context = json.loads(requests[0]["messages"][1]["content"])
    assert len(prompt_context["messages"]) <= 12
    assert len(requests[0]["messages"][1]["content"].encode()) <= 16 * 1024
    assert "raw_evidence" not in json.dumps(prompt_context)


@pytest.mark.asyncio
async def test_chat_responder_is_tool_free_and_forbidden_from_claiming_business_writes():
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return model_response({"text": "可以继续聊，任务状态以侧栏为准。"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reply = await DeepSeekChatResponder(
            ModelConfig(api_key="test"), client, FakeLedger()
        ).respond(context("介绍一下你自己"), run_id="message-chat")

    assert reply.text == "可以继续聊，任务状态以侧栏为准。"
    body = requests[0]
    assert body["temperature"] == 0 and body["max_tokens"] == 1024
    assert body["response_format"] == {"type": "json_object"}
    assert "tools" not in body
    system_prompt = body["messages"][0]["content"]
    assert "不得声称" in system_prompt
    assert "创建" in system_prompt and "批准" in system_prompt


def test_service_models_creates_fresh_conversation_pair_per_operation():
    base_config = {
        "schema_version": "local-service-v1",
        "tokens": [
            {
                "token": "c" * 64,
                "identity": {"tenant_id": "synthetic", "user_id": "conversation-test"},
            }
        ],
    }
    scripted_config = ServiceConfig.model_validate(base_config | {"model_mode": "scripted_double"})
    scripted = ServiceModels("unused", scripted_config, lambda: object())
    first = scripted.conversation()
    second = scripted.conversation()
    assert first is not second
    assert first.classifier is not second.classifier
    assert first.responder is not second.responder

    live_config = ServiceConfig.model_validate(base_config | {"model_mode": "deepseek_live"})
    live = ServiceModels(
        "unused",
        live_config,
        lambda: object(),
        model_config=ModelConfig(api_key="test"),
        ledger=FakeLedger(),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    live.client = client
    try:
        first_live = live.conversation()
        second_live = live.conversation()
        assert first_live.classifier.gateway is not second_live.classifier.gateway
        assert first_live.responder.gateway is not second_live.responder.gateway
        assert first_live.classifier.gateway.client is client
        assert second_live.classifier.gateway.client is client
        assert first_live.classifier.gateway.ledger is second_live.responder.gateway.ledger
    finally:
        import asyncio

        asyncio.run(client.aclose())
