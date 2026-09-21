import asyncio
import json

import httpx
import pytest
from test_tool_model import FakeLedger

from anlan.llm.config import ModelConfig
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.material import DeepSeekAnalyzer
from anlan.workflows.material_contracts import Application

MATERIAL = Application(
    work_location_description="SYNTHETIC：在那边作业。",
    work_object_description="SYNTHETIC：试件 A 接缝",
    work_method_description="SYNTHETIC：电弧焊",
    attachment_description="SYNTHETIC：试件位置示意图",
)
ISSUE = {
    "field": "work_location_description", "kind": "ambiguous", "quote": "那边",
    "reason": "指代不明确", "question": "请明确区域与作业点。",
}


def response(content, finish="stop"):
    return httpx.Response(200, json={
        "model": "deepseek-flash",
        "choices": [{"finish_reason": finish, "message": {
            "content": content, "reasoning_content": "do not store hidden reasoning",
        }}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
    })


async def test_real_adapter_request_and_content_contract_with_http_double():
    requests = []

    def handler(request):
        requests.append(request)
        return response(json.dumps({"issues": [ISSUE]}))

    config = ModelConfig(api_key="test-not-a-real-key", max_requests=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer = DeepSeekAnalyzer(config, client, ledger=FakeLedger())
        result = await analyzer.analyze(MATERIAL)
        assert result.issues[0].source == "model"
        assert result.semantic_status == "checked"
        assert result.usage["total_tokens"] == 80
        payload = json.loads(requests[0].content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 1024
        assert requests[0].url == "https://api.deepseek.com/chat/completions"
        assert "test-not-a-real-key" not in requests[0].content.decode()
        assert "tenant_id" not in requests[0].content.decode()
        assert "reasoning_content" not in result.model_dump_json()
        with pytest.raises(AnalysisFailure, match="budget_exceeded"):
            await analyzer.analyze(MATERIAL)
        assert len(requests) == 1


@pytest.mark.parametrize("content,finish", [
    ("", "stop"), ("not json", "stop"),
    (json.dumps({"issues": [], "approved": True}), "stop"),
    (json.dumps({"issues": [{**ISSUE, "quote": "不存在的原文"}]}), "stop"),
    (json.dumps({"issues": [ISSUE, ISSUE]}), "stop"),
    (json.dumps({"issues": [{**ISSUE, "field": "tenant_id"}]}), "stop"),
    (json.dumps({"issues": []}), "length"),
    (json.dumps({"issues": [{**ISSUE, "kind": "missing"}]}), "stop"),
])
async def test_invalid_output_is_rejected_and_usage_retained(content, finish):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: response(content, finish)
    )) as client:
        analyzer = DeepSeekAnalyzer(ModelConfig(api_key="test"), client, ledger=FakeLedger())
        with pytest.raises(AnalysisFailure, match="invalid_output") as error:
            await analyzer.analyze(MATERIAL)
        assert error.value.usage["total_tokens"] == 80


@pytest.mark.parametrize("failure", ["timeout", "http", "transport", "invalid_envelope"])
async def test_failure_is_bounded_and_does_not_leak_response_or_credentials(failure):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            await asyncio.sleep(1)
        if failure == "transport":
            raise httpx.ConnectError("secret-sentinel", request=request)
        if failure == "invalid_envelope":
            return httpx.Response(200, json={"choices": []})
        return httpx.Response(429, text="secret-sentinel")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer = DeepSeekAnalyzer(ModelConfig(api_key="secret-sentinel", timeout_seconds=.01),
                                    client, ledger=FakeLedger())
        with pytest.raises(AnalysisFailure) as error:
            await analyzer.analyze(MATERIAL)
        assert "secret-sentinel" not in str(error.value)
        assert error.value.category == {
            "timeout": "model_timeout", "http": "model_rate_limited",
            "transport": "model_unavailable", "invalid_envelope": "invalid_output",
        }[failure]
        assert error.value.model == "deepseek-flash"
        assert error.value.prompt_version == "materials-v1"
        assert calls == 1


def test_missing_key_fails_locally_and_config_repr_hides_secret(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        ModelConfig.from_env()
    assert "secret-sentinel" not in repr(ModelConfig(api_key="secret-sentinel"))


async def test_material_adapter_cannot_send_without_shared_ledger():
    sent = []

    def handler(request):
        sent.append(request)
        return response('{"issues":[]}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AnalysisFailure, match="budget_unavailable"):
            await DeepSeekAnalyzer(ModelConfig(api_key="test"), client).analyze(MATERIAL)
    assert sent == []


async def test_material_deep_json_is_recorded_as_invalid_output():
    ledger = FakeLedger()
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="[" * 20000 + "0" + "]" * 20000)
    )) as client:
        with pytest.raises(AnalysisFailure, match="invalid_output"):
            await DeepSeekAnalyzer(ModelConfig(api_key="test"), client,
                                   ledger=ledger).analyze(MATERIAL)
    assert ledger.attempts[0]["status"] == "failed"
