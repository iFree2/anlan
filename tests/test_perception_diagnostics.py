"""Offline evidence for P6 hypotheses; never sends a provider request."""

import json

import httpx
import pytest
from test_events import payload
from test_perception import bundle, candidate
from test_tool_model import FakeLedger, envelope

from anlan.llm.config import ModelConfig
from anlan.llm.perception import DeepSeekPerceptionModel
from anlan.workflows.perception import synthesize_perception
from anlan.workflows.perception_contracts import NOTICE, PerceptionCandidate, build_context


def test_prompt_exposes_exact_schema_and_literal_without_sentence_punctuation():
    context = build_context(payload(), bundle())
    system = context["messages"][0]["content"]
    schema = json.loads(system.split("JSON Schema：\n", 1)[1])
    assert schema == PerceptionCandidate.model_json_schema()
    assert json.dumps(NOTICE, ensure_ascii=False) in system
    assert NOTICE + "。" not in system
    assert context["version"] == "perception-context-v2"
    bad = candidate() | {"notice": NOTICE + "。"}
    with pytest.raises(ValueError):
        PerceptionCandidate.model_validate(bad)


@pytest.mark.parametrize("case", ["json", "missing", "extra", "nested_extra", "envelope",
                                 "reference", "unknown"])
async def test_failure_layers_and_diagnostics_do_not_echo_provider_text(case):
    value = candidate()
    content = None
    if case == "json":
        content = "{secret-sentinel"
        expected = [{"type": "json_invalid", "loc": []}]
    elif case == "missing":
        del value["event_id"]
        expected = [{"type": "missing", "loc": ["event_id"]}]
    elif case == "extra":
        value["secret-sentinel"] = "secret-sentinel"
        expected = [{"type": "extra_forbidden", "loc": ["<extra_field>"]}]
    elif case == "nested_extra":
        value["concerns"][0]["secret-sentinel"] = "secret-sentinel"
        expected = [{"type": "extra_forbidden", "loc": ["concerns", 0, "<extra_field>"]}]
    elif case == "envelope":
        expected = [{"type": "invalid_envelope", "loc": []}]
    elif case == "reference":
        value["concerns"][0]["evidence_ids"] = ["o1"]
    else:
        value["unknown_observation_ids"] = []
    response = envelope({"content": content or json.dumps(value),
                         "reasoning_content": "secret-sentinel"}, "stop")
    if case == "envelope":
        response["choices"] = []
    ledger = FakeLedger()
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response)
    )) as client:
        model = DeepSeekPerceptionModel(ModelConfig(api_key="secret-sentinel"), client, ledger)
        result = await synthesize_perception(payload(), bundle(), model, case)
    if case in {"reference", "unknown"}:
        assert result["stop_reason"] == "unsupported_output"
        assert result["rejected_candidate"] == value
        assert ledger.attempts[0]["status"] == "succeeded"
    else:
        assert result["stop_reason"] == "invalid_output"
        assert result["output_diagnostics"] == expected
        assert ledger.attempts[0]["status"] == "failed"
        assert "secret-sentinel" not in json.dumps(result)
    assert result["candidate"] is None
    assert len(ledger.attempts) == result["requests_this_run"] == 1


@pytest.mark.parametrize("body, expected", [
    ("{secret-sentinel", "outer_json_invalid"),
    ("[]", "invalid_envelope"), ("null", "invalid_envelope"),
    ("x" * 65537, "response_too_large"),
], ids=["json", "array", "null", "oversized"])
async def test_outer_response_diagnostic_is_bounded_and_reset(body, expected):
    ledger = FakeLedger()
    replies = [httpx.Response(200, text=body), httpx.Response(
        200, json=envelope({"content": json.dumps(candidate())}, "stop"))]
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: replies.pop(0)
    )) as client:
        model = DeepSeekPerceptionModel(ModelConfig(api_key="secret-sentinel"), client, ledger)
        result = await synthesize_perception(payload(), bundle(), model, "outer")
        assert result["stop_reason"] == "invalid_output"
        assert result["output_diagnostics"] == [{"type": expected, "loc": []}]
        assert result["requests_this_run"] == 1
        assert "secret-sentinel" not in json.dumps(result)
        good = await synthesize_perception(payload(), bundle(), model, "outer")
        assert good["stop_reason"] == "completed"
        assert good["output_diagnostics"] is None
        assert len(ledger.attempts) == 2
