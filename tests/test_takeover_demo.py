"""Takeover reports must fail closed and preserve partial evidence without secrets."""

import importlib.util
import json
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/takeover_demo.py"


def load():
    assert SCRIPT.exists(), "A reproducible takeover entry point is required"
    spec = importlib.util.spec_from_file_location("takeover_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_directory_is_never_overwritten(tmp_path):
    demo = load()
    sentinel = tmp_path / "report.json"
    sentinel.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        demo.run(tmp_path)
    assert sentinel.read_text() == "original"


@pytest.mark.parametrize("error", [RuntimeError("secret-password"),
                                   subprocess.TimeoutExpired("secret-command", 1)])
def test_failure_saves_stage_without_exception_text(tmp_path, monkeypatch, error):
    demo = load()
    budget = {"total_reserved": 42, "status_counts": {"failed": 2}}
    monkeypatch.setattr(demo, "budget_snapshot", lambda: budget)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(demo, "execute", fail)
    path = tmp_path / "run"
    assert demo.run(path) == 1
    raw = (path / "report.json").read_text(encoding="utf-8")
    report = json.loads(raw)
    assert report["status"] == "failed" and report["failed_stage"] == "materials"
    assert report["error_category"] == type(error).__name__
    assert report["budget_after"] == budget
    assert "secret" not in raw


def test_unavailable_budget_is_unknown_and_prevents_steps(tmp_path, monkeypatch):
    demo = load()

    def unavailable():
        raise RuntimeError("private-dsn")

    monkeypatch.setattr(demo, "budget_snapshot", unavailable)
    monkeypatch.setattr(demo, "execute", lambda *a: pytest.fail("Must not run steps"))
    path = tmp_path / "run"
    assert demo.run(path) == 1
    report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    assert report["budget_before"] is None and report["budget_after"] is None
    assert report["model_request_delta"] is None
    assert report["failed_stage"] == "budget_before"


def test_replay_cannot_turn_missing_outputs_into_model_success():
    demo = load()
    rows = [{"actual": "not_replayable", "matches_expected": True} for _ in range(2)]
    rows += [{"actual": "accepted", "matches_expected": True} for _ in range(4)]
    report = {"status": "completed", "model_requests": 0, "rows": rows,
              "matches_expected": 6, "not_replayable": 2}
    result = demo.validate_step("dev", report)
    assert result == {"contract_matches": 6, "recorded_outputs_replayed": 4,
                      "not_replayable": 2, "new_model_successes": 0}
    report["rows"][0]["matches_expected"] = False
    with pytest.raises(ValueError):
        demo.validate_step("dev", report)


def test_scripted_chain_requires_both_events_and_no_requests():
    demo = load()
    report = {"status": "completed", "mode": "scripted", "requests_this_run": 0,
              "rows": [{"kind": "helmet_missing", "engineering_chain_passed": True},
                       {"kind": "gas_abnormal", "engineering_chain_passed": False}]}
    with pytest.raises(ValueError):
        demo.validate_step("perception", report)
    report["rows"][1]["engineering_chain_passed"] = True
    assert demo.validate_step("perception", report)["engineering_chains"] == 2
    report["requests_this_run"] = 1
    with pytest.raises(ValueError):
        demo.validate_step("perception", report)


def test_execute_binds_source_despite_inherited_pythonpath(tmp_path, monkeypatch):
    demo = load()
    fake = tmp_path / "anlan"
    fake.mkdir()
    (fake / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    probe = tmp_path / "probe.py"
    probe.write_text("import anlan,sys\nfrom pathlib import Path\n"
                     "assert Path(anlan.__file__).resolve().parent == Path(sys.argv[1])\n",
                     encoding="utf-8")
    assert demo.execute([str(probe), str(demo.ROOT / "src/anlan")]) == 0


def test_timeout_cleans_grandchild_before_return(tmp_path, monkeypatch):
    demo = load()
    child = tmp_path / "child.py"
    marker = tmp_path / "late-write"
    child.write_text("import time,sys\nfrom pathlib import Path\n"
                     "time.sleep(2)\nPath(sys.argv[1]).write_text('unexpected')\n",
                     encoding="utf-8")
    parent = tmp_path / "parent.py"
    parent.write_text("import subprocess,sys,time\n"
                      "subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],"
                      "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                      "time.sleep(10)\n", encoding="utf-8")
    original = subprocess.run

    def short_run(*args, **kwargs):
        kwargs["timeout"] = 0.7
        return original(*args, **kwargs)

    # Before the fix this shortens subprocess.run; afterwards the named deadline applies.
    monkeypatch.setattr(demo.subprocess, "run", short_run)
    monkeypatch.setattr(demo, "PROCESS_TIMEOUT_SECONDS", 0.7, raising=False)
    with pytest.raises(subprocess.TimeoutExpired):
        demo.execute([str(parent), str(child), str(marker)])
    time.sleep(2.3)
    assert not marker.exists(), "A grandchild kept executing after the demo deadline"


@pytest.mark.parametrize("fault", ["exit", "invalid_json", "missing", "final_budget"])
def test_incomplete_steps_and_final_budget_cannot_pass(tmp_path, monkeypatch, fault):
    demo = load()
    source = demo.ROOT / "docs/phases/phase-07-takeover-career/evidence/wp01/demo-v1"
    budget = {"total_reserved": 42}
    snapshots = iter([budget, RuntimeError("private-dsn"), budget])

    def snapshot():
        value = next(snapshots) if fault == "final_budget" else budget
        if isinstance(value, Exception):
            raise value
        return value

    def execute(args):
        target = Path(args[-1])
        if fault == "exit":
            return 2
        if fault == "missing":
            return 0
        target.write_bytes((source / target.name).read_bytes()
                           if fault == "final_budget" else b"invalid")
        return 0

    monkeypatch.setattr(demo, "budget_snapshot", snapshot)
    monkeypatch.setattr(demo, "execute", execute)
    target = tmp_path / "run"
    assert demo.run(target) == 1
    report = json.loads((target / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["failed_stage"] == ("budget_after" if fault == "final_budget" else "materials")
    if fault == "final_budget":
        assert len(report["steps"]) == 5
        assert report["budget_after"] == budget  # Recovery must not turn failure into success.
    else:
        assert len(report["steps"]) == 1
