import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_multi_review import bundle
from test_tool_model import FakeLedger, envelope

from anlan.llm.config import ModelConfig
from anlan.llm.evidence_review import DeepSeekEvidenceModel, ScriptedEvidenceModel
from anlan.llm.review_model import DeepSeekReviewModel, ScriptedReviewModel
from anlan.workflows.multi_review import multi_review


async def test_quality_roles_share_only_explicit_trusted_package_before_http():
    ledger = FakeLedger()
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        assert ledger.attempts[-1]["package"] == "P6-WP03"
        body = json.loads(request.content)
        context = {"messages": body["messages"]}
        assert body["max_tokens"] == 1024 and "tools" not in body
        if count == 1:
            value = (await ScriptedReviewModel().generate(context, "risk"))["candidate"]
        else:
            value = (await ScriptedEvidenceModel().generate(context, "audit"))["review"]
        return httpx.Response(200, json=envelope({"content": json.dumps(value)}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        config = ModelConfig(api_key="sentinel", max_requests=1)
        risk = DeepSeekReviewModel(config, client, ledger, work_package="P6-WP03")
        audit = DeepSeekEvidenceModel(config, client, ledger, work_package="P6-WP03")
        with pytest.raises(ValueError):
            await multi_review(bundle(), risk, audit)  # P4 caller cannot silently spend P6.
        assert not ledger.attempts
        result = await multi_review(bundle(), risk, audit, work_package="P6-WP03")
        assert result["work_package"] == "P6-WP03" and result["requests_this_run"] == 2
        assert result["stop_reason"] == "completed"
        for cls in (DeepSeekEvidenceModel, DeepSeekReviewModel):
            with pytest.raises(ValueError):
                cls(config, client, ledger, work_package="P5-WP02")


async def test_gold_is_not_in_judge_context_and_wrong_or_missing_labels_are_not_success():
    from anlan.workflows.judge_calibration import calibration_context, score_calibration

    data = json.loads(Path("evals/judge-v1/cases.json").read_text(encoding="utf-8"))
    case = data["cases"][0]
    context = calibration_context(case, data["rubric"])
    text = json.dumps(context["messages"])
    assert '"gold"' not in text and '"label_origin"' not in text
    candidate = (await ScriptedEvidenceModel().generate(context, "double"))["review"]
    score = score_calibration(candidate, context, case["gold"])
    assert score["correct"] == 1 and score["total"] == 3
    assert score["confusion"]["supported"]["uncertain"] == 1
    candidate["assessments"].pop()
    invalid = score_calibration(candidate, context, case["gold"])
    assert invalid["correct"] == 0 and invalid["invalid"] == 3


async def test_audit_ablation_keeps_same_candidate_and_never_grants_approval():
    from anlan.workflows.judge_calibration import ablate_audit

    value = await multi_review(bundle(), ScriptedReviewModel(), ScriptedEvidenceModel())
    ablated = ablate_audit(value)
    assert ablated["candidate"] == value["candidate"]
    assert ablated["coordination"] == "review_unavailable_requires_human_review"
    assert ablated["model_requests"] == 0
    assert value["audit"] is not None


@pytest.mark.parametrize("snapshot_failure", [False, True])
async def test_experiment_has_eight_reservations_saved_before_http_and_no_gold_leak(
    snapshot_failure,
):
    spec = importlib.util.spec_from_file_location("quality_experiment", "evals/evaluate_quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Ledger(FakeLedger):
        async def snapshot(self):
            if self.attempts and snapshot_failure:
                raise RuntimeError("Injected reconciliation failure")
            return {"total_reserved": len(self.attempts), "total_limit": 100,
                    "package_limit": 10, "packages": {"P6-WP03": len(self.attempts)},
                    "attempts": [a | {"attempt_id": str(i)}
                                 for i, a in enumerate(self.attempts, 1)]}

    ledger, saved = Ledger(), []
    report = {"run_ids": [], "results": [], "judge": [], "mode": "deepseek",
              "requests_this_run": 0}

    def save():
        saved.append(json.loads(json.dumps(report)))

    async def handler(request):
        attempt = ledger.attempts[-1]
        assert attempt["run_id"] in saved[-1]["run_ids"]
        body = json.loads(request.content)
        text = json.dumps(body["messages"])
        assert '"gold"' not in text and '"label_origin"' not in text
        context = {"messages": body["messages"]}
        data = json.loads(body["messages"][1]["content"])
        if "claims" in data:
            result = (await ScriptedEvidenceModel().generate(context, "a"))["review"]
        else:
            result = (await ScriptedReviewModel().generate(context, "r"))["candidate"]
        return httpx.Response(200, json=envelope({"content": json.dumps(result)}, "stop"))

    data = json.loads(Path("evals/judge-v1/cases.json").read_text(encoding="utf-8"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if snapshot_failure:
            with pytest.raises(RuntimeError):
                await module.execute(data, report, save, ledger, client,
                                     ModelConfig(api_key="sentinel", max_requests=1))
            assert report["requests_this_run"] is None
            assert report["requests_observed_lower_bound"] == 8
            assert report["budget_warning"] == "snapshot_unavailable"
            assert report["request_accounting_complete"] is False
            return
        else:
            await module.execute(data, report, save, ledger, client,
                                 ModelConfig(api_key="sentinel", max_requests=1))
    assert report["requests_this_run"] == 8
    assert report["usage"]["total_tokens"] == 240
    assert len(report["judge"]) == 2 and len(report["results"]) == 2


async def test_relative_runpy_entry_keeps_absolute_source_fingerprints(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("quality_relative", "evals/evaluate_quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Ledger:
        async def snapshot(self):
            return {"attempts": [], "total_reserved": 0, "packages": {}}

    monkeypatch.setattr(module, "__file__", "evals/evaluate_quality.py")
    monkeypatch.setattr(module, "database_url", lambda: "unused")
    monkeypatch.setattr(module, "BudgetLedger", lambda dsn: Ledger())
    output = tmp_path / "relative.json"
    assert await module.evaluate(SimpleNamespace(mode="scripted", output=output)) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert "evals/evaluate_quality.py" in report["sources"]
    assert report["requests_this_run"] == 0
