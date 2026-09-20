import importlib.util
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

from anlan.evaluation import score_issues


def test_scoring_preserves_false_positives_misses_and_zero_denominators():
    scores = score_issues(
        [["work_location_description", "ambiguous"], ["attachment_description", "conflict"]],
        [["work_location_description", "ambiguous"], ["work_object_description", "missing"]],
    )
    assert scores == {"tp": 1, "fp": 1, "fn": 1, "precision": .5,
                      "recall": .5, "exact_match": False}
    assert score_issues([], []) == {"tp": 0, "fp": 0, "fn": 0, "precision": None,
                                    "recall": None, "exact_match": True}
    assert score_issues([], [["work_location_description", "ambiguous"]])["fn"] == 1


def test_offline_evaluation_keeps_known_semantic_miss_and_refuses_overwrite(tmp_path):
    output = tmp_path / "evaluation.json"
    command = [sys.executable, "evals/evaluate.py", "--mode", "offline",
               "--output", str(output)]
    kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "timeout": 30,
              "env": {**os.environ, "PYTHONUTF8": "1"}}
    result = subprocess.run(command, **kwargs)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "offline"
    assert [r["scores"]["exact_match"] for r in report["results"]] == [True, True, False]
    assert report["results"][-1]["scores"]["fn"] == 1
    original = output.read_bytes()
    assert subprocess.run(command, **kwargs).returncode == 2
    assert output.read_bytes() == original


def load_runner():
    spec = importlib.util.spec_from_file_location("anlan_eval_runner", Path("evals/evaluate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_live_mode_and_partial_usage_are_reported_with_http_double(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-not-real")
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 3:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"issues":[]}'}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
        })

    client_class = httpx.AsyncClient
    monkeypatch.setattr(runner.httpx, "AsyncClient", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs))
    output = tmp_path / "http-double.json"
    await runner.evaluate(Namespace(mode="deepseek", output=output))
    report = json.loads(output.read_text(encoding="utf-8"))
    assert all(row["state"]["analysis_mode"] == "deepseek" for row in report["results"])
    assert report["configuration"]["requested_model"] == "deepseek-flash"
    assert report["configuration"]["prompt_version"] == "materials-v1"
    assert len(report["configuration"]["prompt_sha256"]) == 64
    assert len(requests) == report["summary"]["request_attempts"] == 3
    assert report["summary"]["semantic_failures"] == 1
    assert report["summary"]["fn"] == 1
    assert report["summary"]["known_prompt_tokens"] == 100
    assert report["summary"]["known_completion_tokens"] == 60
    assert report["summary"]["usage_complete"] is False
    assert report["results"][-1]["state"]["analysis"]["usage"] is None
    assert "test-not-real" not in output.read_text(encoding="utf-8")


async def test_missing_key_does_not_leave_empty_evaluation_file(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    output = tmp_path / "not-started.json"
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        await runner.evaluate(Namespace(mode="deepseek", output=output))
    assert not output.exists()


def test_no_returned_usage_is_unknown_not_zero():
    runner = load_runner()
    rows = [{"state": {"analysis": {"semantic_status": "failed", "usage": None}},
             "scores": {"tp": 0, "fp": 0, "fn": 1, "exact_match": False}}]
    summary = runner.summarize(rows, request_attempts=1)
    assert summary["known_total_tokens"] is None
    assert summary["usage_complete"] is False
