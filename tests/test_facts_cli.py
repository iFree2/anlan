import json
import os
import subprocess
import sys

import pytest
from test_postgres import dsn  # noqa: F401

pytestmark = pytest.mark.postgres


def test_fact_cli_cross_process_preserves_task_and_rejects_other_tenant(dsn, tmp_path):  # noqa: F811
    def invoke(*args, expected=0):
        process = subprocess.run(
            [sys.executable, "-m", "anlan", *args, "--trace", str(tmp_path / "trace.jsonl")],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, "ANLAN_DATABASE_URL": dsn, "PYTHONUTF8": "1"},
        )
        assert process.returncode == expected, process.stderr
        return json.loads(process.stdout) if expected == 0 else process.stderr

    before = invoke("start")
    task = before["task_id"]
    args = ("check-facts", "--task", task, "--refs-file", "examples/synthetic/fact-refs.json",
            "--as-of", "2026-09-20T12:00:00Z", "--mode", "deepseek")
    report = invoke(*args)
    assert [r["outcome"] for r in report["results"]] == ["ok", "ok"]
    invoke(*args, "--tenant", "other", expected=2)
    assert invoke("show", "--task", task) == before
    assert len(invoke("history", "--task", task)["operations"]) == 1


def test_scripted_agent_cli_uses_tool_observations_without_live_requests(dsn, tmp_path):  # noqa: F811
    def invoke(*args):
        result = subprocess.run(
            [sys.executable, "-m", "anlan", *args, "--trace", str(tmp_path / "agent.trace.jsonl")],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, "ANLAN_DATABASE_URL": dsn, "PYTHONUTF8": "1"},
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    before = invoke("start")
    report = invoke("check-facts-agent", "--task", before["task_id"], "--refs-file",
                    "examples/synthetic/fact-refs.json", "--as-of", "2026-09-20T12:00:00Z")
    assert report["mode"] == "scripted_double"
    assert report["requests_this_run"] == 0
    assert report["stop_reason"] == "completed"
    assert invoke("show", "--task", before["task_id"]) == before
