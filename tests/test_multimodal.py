"""Preflight, attribution and uncertain image outputs without real model requests."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from anlan.llm.config import ModelConfig


def module():
    path = Path(__file__).resolve().parents[1] / "evals/evaluate_multimodal.py"
    assert path.exists(), "Bounded image experiment is missing"
    spec = importlib.util.spec_from_file_location("evaluate_multimodal", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def envelope(value):
    return {"model": "synthetic-test", "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(value)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_frozen_inputs_are_separate_and_gold_is_not_sent():
    m = module()
    for case in m.load_dataset()["cases"]:
        image = m.payload(case, "image")
        text = m.payload(case, "structured")
        assert isinstance(text["messages"][-1]["content"], str)
        assert image["messages"][-1]["content"][1]["type"] == "image_url"
        assert '"gold"' not in json.dumps(image)
        assert len(json.dumps(image).encode()) < 32768
        assert image["max_tokens"] == 1024 and image["model"] == "deepseek-flash"
    damaged = dict(case, image_sha256="0" * 64)
    with pytest.raises(ValueError):
        m.payload(damaged, "image")


@pytest.mark.parametrize("value", [
    {"head_observation": "not_visible", "requires_human_review": False},
    {"head_observation": "not_visible", "requires_human_review": True, "approve": True},
    {"head_observation": "unsafe", "requires_human_review": True},
])
def test_rejects_unscoped_output(value):
    with pytest.raises(ValueError):
        module().parse(envelope(value))


async def test_preallocation_and_final_snapshot_failure_preserve_attempt_lower_bound():
    m = module()

    class Ledger:
        count = 0
        snapshots = 0

        async def snapshot(self):
            self.snapshots += 1
            if self.snapshots > 1:
                raise RuntimeError("private-dsn")
            return {"total_reserved": 42, "total_limit": 100, "package_limit": 10,
                    "packages": {}}

        async def reserve(self, package, run_id):
            assert package == "P7-WP03"
            self.count += 1
            return f"attempt-{self.count}"

        async def finish(self, attempt, status, **kwargs):
            assert status == "succeeded"

    ledger = Ledger()
    calls = []

    def respond(request):
        calls.append(request)
        assert ledger.count == len(calls)
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        return httpx.Response(200, json=envelope({"head_observation": "not_visible",
                                                 "requires_human_review": True}))

    report = {"rows": [], "budget_after": None}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await m.execute(m.load_dataset(), report, lambda: None, ledger, client,
                        ModelConfig(api_key="synthetic-not-real", max_requests=2))
    assert len(calls) == 4
    assert report["status"] == "completed_budget_unknown"
    assert report["observed_attempt_lower_bound"] == 4
    assert report["project_total_after"] is None
    assert report["budget_after"] is None
    assert report["rows"][0]["matches_gold"] is False


@pytest.mark.parametrize("already_used", [1, 4])
async def test_any_previous_experiment_attempt_prevents_whole_run_repeat(already_used):
    m = module()

    class Ledger:
        async def snapshot(self):
            return {"total_reserved": 42 + already_used, "total_limit": 100,
                    "package_limit": 10, "packages": {"P7-WP03": already_used}}

        async def reserve(self, *args):
            pytest.fail("Previous attempt must prevent reserving another experiment")

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: pytest.fail("Repeated experiment sent HTTP")
    )) as client:
        with pytest.raises(ValueError):
            await m.execute(m.load_dataset(), {"rows": [], "budget_after": None}, lambda: None,
                            Ledger(), client, ModelConfig(api_key="synthetic", max_requests=2))
