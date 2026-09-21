import json

import httpx
import pytest

from anlan.llm.config import ModelConfig
from anlan.llm.contracts import AnalysisFailure


class FakeLedger:
    """HTTP替身的显式账本替身，不写生产计数。"""

    def __init__(self):
        self.attempts = []

    async def reserve(self, package, run_id):
        self.attempts.append({"package": package, "run_id": run_id, "status": "reserved"})
        return str(len(self.attempts))

    async def finish(self, attempt_id, status, usage=None, error=None):
        self.attempts[int(attempt_id) - 1].update(status=status, usage=usage, error=error)


async def test_explicit_p3_package_is_reserved_before_http():
    from anlan.llm.tool_model import DeepSeekToolModel
    ledger = FakeLedger()

    def handler(request):
        assert ledger.attempts[0]["package"] == "P3-WP02"
        return httpx.Response(200, json=envelope({"content": None, "tool_calls": [call()]}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekToolModel(ModelConfig(api_key="test"), client, ledger,
                                  include_knowledge=True, work_package="P3-WP02")
        await model.next([{"role": "user", "content": "SYNTHETIC"}], "test-p3")
    assert ledger.attempts[0]["status"] == "succeeded"


def envelope(message, finish="tool_calls"):
    return {"choices": [{"finish_reason": finish, "message": {
        "role": "assistant", "reasoning_content": "hidden-sentinel", **message}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}


def call(name="query_area_status", arguments='{"area_id":"area-001"}', ident="call-1"):
    return {"id": ident, "type": "function", "function": {
        "name": name, "arguments": arguments}}


async def test_real_tool_protocol_with_http_double_reserves_before_send():
    from anlan.llm.tool_model import DeepSeekToolModel
    ledger = FakeLedger()
    sent = []

    def handler(request):
        assert ledger.attempts[0]["status"] == "reserved"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=envelope({"content": None, "tool_calls": [call()]}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekToolModel(ModelConfig(api_key="secret-sentinel"), client, ledger)
        turn = await model.next([{"role": "user", "content": "SYNTHETIC"}], "run-test")
    assert turn.calls[0].name == "query_area_status"
    assert turn.usage["total_tokens"] == 30
    assert ledger.attempts[0]["status"] == "succeeded"
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert sent[0]["max_tokens"] == 1024
    assert {t["function"]["name"] for t in sent[0]["tools"]} == {
        "query_worker_qualification", "query_area_status"}
    assert "hidden-sentinel" not in turn.model_dump_json()
    assert "secret-sentinel" not in json.dumps(sent)


@pytest.mark.parametrize("kind", [
    "http", "bad_json", "length", "duplicate_id", "oversized", "deep_json",
])
async def test_bad_response_consumes_reserved_attempt_and_retains_failure(kind):
    from anlan.llm.tool_model import DeepSeekToolModel
    ledger = FakeLedger()

    def handler(request):
        if kind == "http":
            return httpx.Response(429, text="secret-sentinel")
        if kind == "bad_json":
            return httpx.Response(200, text="not json")
        if kind == "oversized":
            return httpx.Response(200, text="x" * 65537)
        if kind == "deep_json":
            return httpx.Response(200, text="[" * 20000 + "0" + "]" * 20000)
        return httpx.Response(200, json=envelope(
            {"content": None, "tool_calls": [call(), call()] if kind == "duplicate_id" else []},
            finish="length" if kind == "length" else "tool_calls"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekToolModel(ModelConfig(api_key="secret-sentinel"), client, ledger)
        with pytest.raises(AnalysisFailure) as failed:
            await model.next([{"role": "user", "content": "SYNTHETIC"}], "run-test")
    assert "secret-sentinel" not in str(failed.value)
    assert len(ledger.attempts) == 1
    assert ledger.attempts[0]["status"] == "failed"


async def test_oversized_input_or_budget_failure_never_sends_request():
    from anlan.llm.tool_model import DeepSeekToolModel
    ledger = FakeLedger()

    async def unavailable(*args):
        raise RuntimeError("credential-sentinel")

    def never_send(request):
        pytest.fail("request sent without valid input/budget")

    async with httpx.AsyncClient(transport=httpx.MockTransport(never_send)) as client:
        model = DeepSeekToolModel(ModelConfig(api_key="test"), client, ledger)
        with pytest.raises(AnalysisFailure, match="input_too_large"):
            await model.next([{"role": "user", "content": "x" * 32769}], "run-test")
        assert not ledger.attempts
        ledger.reserve = unavailable
        with pytest.raises(AnalysisFailure, match="budget_unavailable"):
            await model.next([{"role": "user", "content": "SYNTHETIC"}], "run-test")


async def test_final_json_is_schema_checked():
    from anlan.llm.tool_model import DeepSeekToolModel
    data = {"summary": "仍需人工复核", "evidence_call_ids": ["call-1"]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=envelope(
            {"content": json.dumps(data)}, finish="stop"))
    )) as client:
        turn = await DeepSeekToolModel(ModelConfig(api_key="test"), client, FakeLedger()).next(
            [{"role": "user", "content": "SYNTHETIC"}], "run-test")
    assert not turn.calls
    assert turn.final.summary == data["summary"]
