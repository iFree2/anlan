import importlib.util
import sys
from pathlib import Path


def test_gate_module_exists():
    assert Path("evals/phase03_gate.py").is_file()


def test_gate_rejects_missing_duplicate_rows_and_new_reservations():
    sys.path.insert(0, str(Path("evals").resolve()))
    spec = importlib.util.spec_from_file_location("p3_gate", "evals/phase03_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    budget = {"attempts": [], "total_reserved": 0}
    report = {"status": "completed", "mode": "scripted", "results": [],
              "budget_before": budget, "budget_after": budget, "requests_this_run": 0}
    assert not module.review_passes(report)
    row = {"case_id": "rag-001-current", "arm": "with_memory", "material_unchanged": True,
           "scores": {k: True for k in module.SCORES},
           "evidence": {"mode": "scripted_double", "stop_reason": "completed",
                        "context": {"bytes_used": 100, "budget_bytes": 24000},
                        "requests_this_run": 0, "trace_warning": None}}
    report["results"] = [row] * 9
    assert not module.review_passes(report)
