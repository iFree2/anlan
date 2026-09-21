import asyncio
import copy
import json

import httpx
import pytest
from test_context import NOW, OBSERVATIONS, SNAPSHOT, WHO, build
from test_review import candidate
from test_tool_model import FakeLedger, envelope

from anlan.llm.config import ModelConfig
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.review_model import DeepSeekReviewModel, ScriptedReviewModel


def bundle():
    return {"identity": WHO.model_dump(), "snapshot": copy.deepcopy(SNAPSHOT),
            "observations": copy.deepcopy(OBSERVATIONS), "memories": [], "warnings": [],
            "as_of": NOW.isoformat(), "question": "监护要求？"}


async def test_p4_package_is_reserved_before_http_and_old_default_is_unchanged():
    ledger = FakeLedger()

    def handler(request):
        assert ledger.attempts[-1]["package"] == "P4-WP02"
        return httpx.Response(200, json=envelope({"content": json.dumps(candidate())}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekReviewModel(ModelConfig(api_key="sentinel"), client, ledger,
                                    work_package="P4-WP02")
        await model.generate(build(), "child-run")
        assert DeepSeekReviewModel(ModelConfig(api_key="sentinel"), client, ledger
                                   ).gateway.work_package == "P3-WP03"


async def test_independent_context_and_restricted_coordination():
    from anlan.llm.evidence_review import ScriptedEvidenceModel
    from anlan.workflows.multi_review import multi_review
    result = await multi_review(bundle(), ScriptedReviewModel(), ScriptedEvidenceModel())
    assert result["stop_reason"] == "completed"
    assert result["coordination"] == "disputed_requires_human_review"
    assert len(result["children"]) == 2 and result["model_steps"] == 2
    data = json.loads(result["audit_context"]["messages"][1]["content"])
    assert "preferences" not in data and "history" not in data
    assert "fields" not in data["task"]
    assert [c["claim_id"] for c in data["claims"]] == ["c1", "c2", "c3"]
    assert result["candidate"] == result["risk"]["candidate"]
    assert result["requests_this_run"] == 0
    for child in result["children"]:
        assert child["parent_run_id"] == result["run_id"]


@pytest.mark.parametrize("change", ["missing_claim", "duplicate", "fake_quote", "missing_unknown",
                                    "unsupported_source", "approve"])
async def test_audit_contract_rejects_omissions_and_forgery(change):
    from anlan.llm.evidence_review import (
        EvidenceReview,
        ScriptedEvidenceModel,
        build_audit_context,
        validate_audit,
    )
    context = build_audit_context(build(), candidate())
    value = (await ScriptedEvidenceModel().generate(context, "run"))["review"]
    if change == "missing_claim":
        value["assessments"].pop()
    elif change == "duplicate":
        value["assessments"][1]["claim_id"] = value["assessments"][0]["claim_id"]
    elif change == "fake_quote":
        value["assessments"][0]["knowledge_citations"] = [
            {"chunk_id": "chunk-1", "quote": "伪造"}]
    elif change == "missing_unknown":
        value["unknown_observation_ids"] = []
    elif change == "unsupported_source":
        value["assessments"][0].update(verdict="supported", observation_ids=[],
                                        knowledge_citations=[])
    else:
        value["approved"] = True
    with pytest.raises(ValueError):
        validate_audit(EvidenceReview.model_validate(value), context)


@pytest.mark.parametrize("budget", [0, 1, 2])
async def test_parent_step_budget_shared_by_roles(budget):
    from anlan.llm.evidence_review import ScriptedEvidenceModel
    from anlan.workflows.multi_review import ReviewLimits, multi_review
    result = await multi_review(bundle(), ScriptedReviewModel(), ScriptedEvidenceModel(),
                                 limits=ReviewLimits(model_steps=budget))
    assert result["model_steps"] == budget
    assert result["stop_reason"] == ("completed" if budget == 2 else "parent_model_budget_exceeded")
    assert result["observations"] == OBSERVATIONS


async def test_audit_failure_preserves_risk_and_observations():
    from anlan.workflows.multi_review import multi_review

    class Failed:
        mode = "failure_double"

        async def generate(self, *args):
            raise AnalysisFailure("model_timeout")

    result = await multi_review(bundle(), ScriptedReviewModel(), Failed())
    assert result["stop_reason"] == "model_timeout"
    assert result["candidate"] is not None and result["audit"] is None
    assert result["coordination"] == "review_unavailable_requires_human_review"


@pytest.mark.parametrize("external", [False, True])
async def test_cancel_during_second_role(external):
    from anlan.workflows.multi_review import multi_review
    entered, cleanup, event = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Slow:
        mode = "slow_double"

        async def generate(self, *args):
            entered.set()
            try:
                await asyncio.sleep(10)
            finally:
                cleanup.set()

    task = asyncio.create_task(multi_review(bundle(), ScriptedReviewModel(), Slow(),
                                            cancel_event=event))
    await asyncio.wait_for(entered.wait(), 2)
    if external:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        event.set()
        result = await task
        assert result["stop_reason"] == "cancelled" and result["candidate"] is not None
    assert cleanup.is_set()


async def test_deadline_retains_reserved_attempt_and_discards_late_audit():
    from anlan.llm.evidence_review import DeepSeekEvidenceModel
    from anlan.workflows.multi_review import ReviewLimits, multi_review
    ledger = FakeLedger()

    async def handler(request):
        await asyncio.sleep(10)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        audit = DeepSeekEvidenceModel(ModelConfig(api_key="sentinel"), client, ledger)
        result = await multi_review(bundle(), ScriptedReviewModel(), audit,
                                     limits=ReviewLimits(timeout_seconds=0.05))
    assert result["stop_reason"] == "parent_deadline_exceeded"
    assert result["requests_this_run"] == 1 and ledger.attempts[0]["status"] == "reserved"
    assert result["children"][1]["attempt_id"] == "1"
    assert result["candidate"] is not None


async def test_wrong_package_rejected_before_any_request():
    from anlan.llm.evidence_review import ScriptedEvidenceModel
    from anlan.workflows.multi_review import multi_review
    ledger = FakeLedger()
    async with httpx.AsyncClient() as client:
        model = DeepSeekReviewModel(ModelConfig(api_key="sentinel"), client, ledger)
        with pytest.raises(ValueError, match="P4-WP02"):
            await multi_review(bundle(), model, ScriptedEvidenceModel())
    assert ledger.attempts == []


async def test_rejected_risk_does_not_invoke_reviewer():
    from anlan.llm.evidence_review import ScriptedEvidenceModel
    from anlan.workflows.multi_review import multi_review

    class Invalid(ScriptedReviewModel):
        async def generate(self, context, run_id):
            value = await super().generate(context, run_id)
            value["candidate"]["claims"][0]["observation_ids"] = ["forged"]
            return value

    result = await multi_review(bundle(), Invalid(), ScriptedEvidenceModel())
    assert result["model_steps"] == 1 and result["stop_reason"] == "unsupported_output"
    assert result["risk"]["rejected_candidate"] is not None


async def test_unexpected_http_adapter_failure_retains_reserved_attempt():
    from anlan.llm.evidence_review import DeepSeekEvidenceModel
    from anlan.workflows.multi_review import multi_review
    ledger = FakeLedger()
    client = httpx.AsyncClient()
    await client.aclose()
    result = await multi_review(bundle(), ScriptedReviewModel(),
        DeepSeekEvidenceModel(ModelConfig(api_key="sentinel"), client, ledger))
    assert result["stop_reason"] == "role_error" and result["candidate"] is not None
    assert result["requests_this_run"] == 1 and ledger.attempts[0]["status"] == "reserved"
    assert "sentinel" not in json.dumps(result)


async def test_malformed_reviewer_adapter_result_preserves_risk():
    from anlan.workflows.multi_review import multi_review

    class Malformed:
        mode = "malformed_double"

        async def generate(self, *args):
            return {"missing_review": True}

    result = await multi_review(bundle(), ScriptedReviewModel(), Malformed())
    assert result["stop_reason"] == "unsupported_audit" and result["candidate"] is not None


async def test_synthesis_report_package_matches_actual_gateway():
    from anlan.workflows.review import synthesize
    ledger = FakeLedger()

    def handler(request):
        return httpx.Response(200, json=envelope({"content": json.dumps(candidate())}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekReviewModel(ModelConfig(api_key="sentinel"), client, ledger,
                                    work_package="P4-WP02")
        result = await synthesize(bundle(), model)
    assert result["work_package"] == ledger.attempts[0]["package"] == "P4-WP02"


async def test_two_real_gateway_adapters_share_package_and_parent_budget():
    from anlan.llm.evidence_review import DeepSeekEvidenceModel, ScriptedEvidenceModel
    from anlan.workflows.multi_review import multi_review
    ledger = FakeLedger()

    async def handler(request):
        assert ledger.attempts[-1]["package"] == "P4-WP02"
        data = json.loads(request.content)
        context = {"messages": data["messages"]}
        assert data["max_tokens"] == 1024 and "tools" not in data
        if len(ledger.attempts) == 1:
            value = (await ScriptedReviewModel().generate(context, "double"))["candidate"]
        else:
            value = (await ScriptedEvidenceModel().generate(context, "double"))["review"]
        return httpx.Response(200, json=envelope({"content": json.dumps(value)}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        config = ModelConfig(api_key="sentinel")
        result = await multi_review(bundle(),
            DeepSeekReviewModel(config, client, ledger, work_package="P4-WP02"),
            DeepSeekEvidenceModel(config, client, ledger))
    assert result["stop_reason"] == "completed" and result["requests_this_run"] == 2
    assert all(a["status"] == "succeeded" for a in ledger.attempts)
    assert {a["run_id"] for a in ledger.attempts} == {
        result["run_id"] + ":risk", result["run_id"] + ":evidence"}


async def test_oversized_audit_context_does_not_trim_required_evidence():
    from anlan.context.assembly import ContextBudgetExceeded
    from anlan.llm.evidence_review import build_audit_context
    with pytest.raises(ContextBudgetExceeded):
        build_audit_context(build(), candidate(), budget_bytes=10)


async def test_completed_coordination_trace_is_not_an_error(tmp_path):
    from anlan.infrastructure.trace import JsonlTrace
    from anlan.llm.evidence_review import ScriptedEvidenceModel
    from anlan.workflows.multi_review import multi_review
    path = tmp_path / "trace.jsonl"
    await multi_review(bundle(), ScriptedReviewModel(), ScriptedEvidenceModel(),
                       trace=JsonlTrace(path))
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "multi_review_finished" and record["error"] is None
