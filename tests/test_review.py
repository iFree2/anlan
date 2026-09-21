import copy
import importlib.util
import json

import httpx
import pytest
from test_context import NOW, OBSERVATIONS, SNAPSHOT, WHO, build
from test_tool_model import FakeLedger, envelope

from anlan.llm.config import ModelConfig
from anlan.llm.contracts import AnalysisFailure


def test_review_module_exists():
    assert importlib.util.find_spec("anlan.workflows.review") is not None


def candidate():
    return {"claims": [
        {"text": "区域记录已过期，当前情况未知", "observation_ids": ["o1"],
         "knowledge_citations": []},
        {"text": "示例监护依据", "observation_ids": ["o2"],
         "knowledge_citations": [{"chunk_id": "chunk-1", "quote": "SYNTHETIC示例监护"}]}],
        "unknown_observation_ids": ["o1"],
        "presentation": {"detail_level": "brief", "presentation_order": "unknowns_first"},
        "notice": "待人工复核；不是作业批准"}


@pytest.mark.parametrize("change", ["missing_source", "forged_quote", "invisible_chunk",
                                    "missing_unknown", "missing_observation", "approved_field",
                                    "invalid_preference", "blank_claim"])
def test_reject_unsupported_claims_and_missing_unknowns(change):
    from anlan.workflows.review_contracts import ReviewCandidate, validate_candidate
    value = candidate()
    if change == "missing_source":
        value["claims"][0]["observation_ids"] = []
    elif change == "forged_quote":
        value["claims"][1]["knowledge_citations"][0]["quote"] = "不存在的原文"
    elif change == "invisible_chunk":
        value["claims"][1]["knowledge_citations"][0]["chunk_id"] = "trimmed"
    elif change == "missing_unknown":
        value["unknown_observation_ids"] = []
    elif change == "missing_observation":
        value["claims"] = value["claims"][1:]
    elif change == "approved_field":
        value["approved"] = True
    elif change == "invalid_preference":
        value["presentation"]["detail_level"] = "hide_unknowns"
    else:
        value["claims"][0]["text"] = " "
    with pytest.raises(ValueError):
        validate_candidate(ReviewCandidate.model_validate(value), build())


async def test_gateway_fixed_package_before_http_and_candidate_validation():
    from anlan.llm.review_model import DeepSeekReviewModel
    ledger = FakeLedger()

    def handler(request):
        assert ledger.attempts[0]["package"] == "P3-WP03"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash" and payload["max_tokens"] == 1024
        assert "tools" not in payload
        return httpx.Response(200, json=envelope({"content": json.dumps(candidate())}, "stop"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekReviewModel(ModelConfig(api_key="secret-sentinel"), client, ledger)
        result = await model.generate(build(), "test-run")
    assert result["candidate"]["unknown_observation_ids"] == ["o1"]
    assert ledger.attempts[0]["status"] == "succeeded"
    assert "secret-sentinel" not in json.dumps(result)


async def test_synthesis_failure_and_budget_overflow_preserve_observations():
    from anlan.workflows.review import synthesize
    bundle = {"identity": WHO.model_dump(), "snapshot": SNAPSHOT,
              "observations": OBSERVATIONS, "memories": [], "warnings": [],
              "as_of": NOW.isoformat()}
    original = copy.deepcopy(bundle)

    class Failure:
        mode = "explicit_failure_double"
        calls = 0

        async def generate(self, context, run_id):
            self.calls += 1
            raise AnalysisFailure("model_timeout")

    model = Failure()
    result = await synthesize(bundle, model)
    assert result["stop_reason"] == "model_timeout" and result["candidate"] is None
    assert result["observations"] == OBSERVATIONS
    too_large = await synthesize(bundle, model, budget_bytes=1)
    assert too_large["stop_reason"] == "context_budget_exceeded" and model.calls == 1
    assert bundle == original


async def test_unauthorized_task_never_reaches_tools_or_memory():
    from anlan.common.errors import AccessDenied
    from anlan.workflows.review import collect_review

    class Denied:
        async def get(self, identity, task_id):
            raise AccessDenied("denied")

    class Never:
        def __getattr__(self, name):
            raise AssertionError("unauthorized dependency touched")

    with pytest.raises(AccessDenied):
        await collect_review(Denied(), WHO, "task", {}, "question", Never(), Never(), Never())


async def test_trace_records_metadata_and_export_failure_does_not_lose_result(tmp_path):
    from anlan.infrastructure.trace import JsonlTrace
    from anlan.llm.review_model import ScriptedReviewModel
    from anlan.workflows.review import synthesize

    class BrokenExporter:
        def export(self, record):
            raise RuntimeError("injected")

    path = tmp_path / "review.jsonl"
    bundle = {"identity": WHO.model_dump(), "snapshot": SNAPSHOT,
              "observations": OBSERVATIONS, "memories": [], "warnings": [],
              "as_of": NOW.isoformat()}
    report = await synthesize(bundle, ScriptedReviewModel(),
                               trace=JsonlTrace(path, exporter=BrokenExporter()))
    assert report["stop_reason"] == "completed"
    assert report["trace_warning"] == "trace_export_failed"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "awaiting_review"
    assert "candidate" not in record and "messages" not in record


async def test_explicit_question_reaches_synthesis_context():
    from anlan.llm.review_model import ScriptedReviewModel
    from anlan.workflows.review import synthesize
    bundle = {"identity": WHO.model_dump(), "snapshot": SNAPSHOT,
              "observations": OBSERVATIONS, "memories": [], "warnings": [],
              "as_of": NOW.isoformat(), "question": "SYNTHETIC监护要求？"}
    report = await synthesize(bundle, ScriptedReviewModel())
    data = json.loads(report["context"]["messages"][1]["content"])
    assert data.get("knowledge_question") == bundle["question"]


async def test_collection_retains_earlier_fact_trace_warning(monkeypatch):
    from types import SimpleNamespace

    from anlan.workflows import review

    class Service:
        async def get(self, identity, task_id):
            return SNAPSHOT

    class Memory:
        async def list_active(self, identity):
            return []

    async def facts(*args):
        return {"revision": SNAPSHOT["revision"], "source_run_id": SNAPSHOT["run_id"],
                "results": [], "trace_warning": "trace_write_failed"}

    async def knowledge(*args):
        return SimpleNamespace(model_dump=lambda **kwargs: OBSERVATIONS[-1])

    monkeypatch.setattr(review, "check_facts", facts)
    monkeypatch.setattr(review, "query_knowledge", knowledge)
    bundle = await review.collect_review(Service(), WHO, "task", {}, "SYNTHETIC问题",
                                         SimpleNamespace(clock=lambda: NOW), None, Memory())
    assert "fact_trace_write_failed" in bundle["warnings"]
