import json
import os
import subprocess
import sys


def test_cli_demo_is_runnable_and_shows_revisions(tmp_path):
    trace = tmp_path / "trace.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "anlan", "demo", "--trace", str(trace)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert result.returncode == 0, result.stderr
    snapshots = [json.loads(line) for line in result.stdout.splitlines()]
    assert [s["revision"] for s in snapshots] == [1, 2, 3]
    assert snapshots[-1]["status"] == "awaiting_review"
    assert all(s["data_origin"] == "SYNTHETIC" for s in snapshots)
    assert all(s["mode"] == "offline" for s in snapshots)
    assert len(trace.read_text(encoding="utf-8").splitlines()) == 3
