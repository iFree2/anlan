import asyncio
import copy
import json

import httpx
import pytest
from test_events import payload
from test_tool_model import FakeLedger, envelope

from anlan.llm.config import ModelConfig
from anlan.llm.contracts import AnalysisFailure


def bundle():
    return {
        "snapshot": {
            "task_id": "task",
            "revision": 1,
            "run_id": "material-run",
            "status": "awaiting_review",
            "fields": {"description": "SYNTHETIC"},
        },
        "observations": [
            {"tool": "query_worker_qualification", "outcome": "ok", "facts": {}},
            {"tool": "query_area_status", "outcome": "unknown", "reason": "expired"},
            {
                "tool": "query_knowledge",
                "outcome": "ok",
                "citations": [{"chunk_id": "k1", "quote": "SYNTHETIC示例依据，需人工复核"}],
            },
        ],
        "as_of": "2026-09-22T04:00:00Z",
        "collection": {"stop_reason": "completed"},
    }


def candidate():
    return {
        "event_id": "event-1",
        "concerns": [
            {"category": "helmet_missing", "evidence_ids": ["e1"]},
            {"category": "evidence_gap", "evidence_ids": ["o2"]},
        ],
        "unknown_observation_ids": ["o2"],
        "next_steps": ["verify_event_on_site", "review_evidence_with_safety_manager"],
        "notice": "感知辅助候选，仍需人工确认；不改变原始报警",
    }


@pytest.mark.parametrize(
    "change",
    [
        "event",
        "kind",
        "source",
        "missing_unknown",
        "approval",
        "control_step",
        "text_instruction",
        "missing_event",
    ],
)
def test_perception_candidate_rejects_untrusted_actions_and_unsupported_refs(change):
    from anlan.workflows.perception_contracts import build_context, validate_candidate

    value = candidate()
    if change == "event":
        value["event_id"] = "other"
    elif change == "kind":
        value["concerns"][0]["category"] = "gas_abnormal"
    elif change == "source":
        value["concerns"][0]["evidence_ids"] = ["invented"]
    elif change == "missing_unknown":
        value["unknown_observation_ids"] = []
    elif change == "approval":
        value["approved"] = True
    elif change == "control_step":
        value["next_steps"] = ["close_valve"]
    elif change == "text_instruction":
        value["concerns"][0]["text"] = "关闭报警"
    else:
        value["concerns"].pop(0)
    with pytest.raises(ValueError):
        validate_candidate(value, build_context(payload(), bundle()))


async def test_scripted_and_live_adapter_fixed_new_budget_package_before_http():
    from anlan.llm.perception import DeepSeekPerceptionModel, ScriptedPerceptionModel
    from anlan.workflows.perception_contracts import build_context, validate_candidate

    context = build_context(payload(), bundle())
    scripted = await ScriptedPerceptionModel().generate(context, "run")
    assert validate_candidate(scripted["candidate"], context)["event_id"] == "event-1"
    ledger = FakeLedger()

    def handler(request):
        assert ledger.attempts[-1]["package"] == "P5-WP02"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash" and body["max_tokens"] == 1024
        assert "tools" not in body and len(request.content) <= 32768
        return httpx.Response(200, json=envelope({"content": json.dumps(candidate())}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekPerceptionModel(ModelConfig(api_key="sentinel"), client, ledger)
        result = await model.generate(context, "perception-run")
    assert result["candidate"] == candidate()
    assert ledger.attempts[0]["status"] == "succeeded"


@pytest.mark.parametrize("mode", ["timeout", "ordinary_failure", "model_failure", "overflow"])
async def test_failure_keeps_event_and_collected_evidence(mode):
    from anlan.workflows.perception import synthesize_perception

    class Failure:
        mode = "explicit_failure_double"
        calls = 0

        async def generate(self, context, run_id):
            self.calls += 1
            if mode == "timeout":
                await asyncio.sleep(1)
            if mode == "model_failure":
                raise AnalysisFailure("model_unavailable")
            raise RuntimeError("injected model failure")

    event, data, model = payload(), bundle(), Failure()
    if mode == "overflow":
        data["snapshot"]["fields"]["description"] = "很长" * 20000
    original = copy.deepcopy(data)
    result = await synthesize_perception(event, data, model, "run", timeout_seconds=0.01)
    assert result["candidate"] is None and result["stop_reason"] != "completed"
    assert result["event"] == event and result["observations"] == original["observations"]
    assert data == original and model.calls == (0 if mode == "overflow" else 1)


async def test_stopped_collection_does_not_call_model():
    from anlan.llm.perception import ScriptedPerceptionModel
    from anlan.workflows.perception import synthesize_perception

    data = bundle()
    data["collection"]["stop_reason"] = "cancelled"
    result = await synthesize_perception(payload(), data, ScriptedPerceptionModel(), "run")
    assert result["candidate"] is None and result["model_steps"] == 0


async def test_parent_cancellation_is_not_swallowed():
    from anlan.workflows.perception import synthesize_perception

    class Cancelled:
        mode = "explicit_cancel_double"

        async def generate(self, context, run_id):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await synthesize_perception(payload(), bundle(), Cancelled(), "run")


async def test_previous_request_is_not_attributed_to_overflow():
    from anlan.llm.perception import DeepSeekPerceptionModel
    from anlan.workflows.perception import synthesize_perception

    ledger = FakeLedger()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=envelope({"content": json.dumps(candidate())}, "stop")
            )
        )
    ) as client:
        model = DeepSeekPerceptionModel(ModelConfig(api_key="sentinel"), client, ledger)
        first = await synthesize_perception(payload(), bundle(), model, "first")
        assert first["requests_this_run"] == 1
        large = bundle()
        large["snapshot"]["fields"]["description"] = "长" * 30000
        second = await synthesize_perception(payload(), large, model, "second")
        assert second["requests_this_run"] == 0 and second["attempt_id"] is None


async def test_cancelled_waiter_has_no_attempt_from_concurrent_run():
    from anlan.llm.perception import DeepSeekPerceptionModel
    from anlan.workflows.perception_contracts import build_context

    ledger, started, release = FakeLedger(), asyncio.Event(), asyncio.Event()

    async def handler(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json=envelope({"content": json.dumps(candidate())}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekPerceptionModel(ModelConfig(api_key="sentinel"), client, ledger)
        context = build_context(payload(), bundle())
        first = asyncio.create_task(model.generate(context, "first"))
        await started.wait()
        second = asyncio.create_task(model.generate(context, "second"))
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert model.attempt_for("second") is None and len(ledger.attempts) == 1
        release.set()
        await first
        assert model.attempt_for("first") is not None


@pytest.mark.parametrize("returns_immediately", [True, False])
async def test_explicit_cancel_signal_during_model_discards_late_candidate(returns_immediately):
    from anlan.llm.perception import ScriptedPerceptionModel
    from anlan.workflows.perception import synthesize_perception

    cancel = asyncio.Event()

    class Cancelling(ScriptedPerceptionModel):
        async def generate(self, context, run_id):
            cancel.set()
            if not returns_immediately:
                await asyncio.sleep(5)
            return await super().generate(context, run_id)

    result = await synthesize_perception(
        payload(), bundle(), Cancelling(), "cancel-run", cancel_event=cancel
    )
    assert result["stop_reason"] == "cancelled" and result["candidate"] is None


async def test_cancel_during_model_child_cleanup_wins_over_candidate():
    from anlan.llm.perception import ScriptedPerceptionModel
    from anlan.workflows.perception import synthesize_perception

    signal = asyncio.Event()
    setters = []

    async def later():
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        signal.set()

    class Racy(ScriptedPerceptionModel):
        async def generate(self, context, run_id):
            setters.append(asyncio.create_task(later()))
            return await super().generate(context, run_id)

    value = await synthesize_perception(payload(), bundle(), Racy(), "cleanup", cancel_event=signal)
    await asyncio.gather(*setters)
    assert signal.is_set() and value["stop_reason"] == "cancelled"


async def test_schema_failure_retains_field_diagnostics_without_raw_response():
    from anlan.llm.perception import DeepSeekPerceptionModel
    from anlan.workflows.perception import synthesize_perception

    malformed = candidate()
    del malformed["event_id"]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=envelope(
                    {
                        "content": json.dumps(malformed),
                        "reasoning_content": "never retain this sentinel",
                    },
                    "stop",
                ),
            )
        )
    ) as client:
        model = DeepSeekPerceptionModel(
            ModelConfig(api_key="secret-sentinel"), client, FakeLedger()
        )
        result = await synthesize_perception(payload(), bundle(), model, "invalid-schema")
    assert result["stop_reason"] == "invalid_output"
    assert result["output_diagnostics"] == [{"type": "missing", "loc": ["event_id"]}]
    assert "sentinel" not in json.dumps(result)
