import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path


def gate():
    sys.path.insert(0, str(Path("evals").resolve()))
    spec = importlib.util.spec_from_file_location("phase05_gate", "evals/phase05_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_service_gate_rejects_missing_types_hidden_requests_and_failed_restart():
    source = Path("docs/phases/phase-05-events-service/evidence/wp03/clean-service-v2.json")
    report = json.loads(source.read_text(encoding="utf-8"))
    validate = gate().service_passes
    assert validate(report)
    changed = deepcopy(report)
    changed["rows"].pop()
    assert not validate(changed)
    changed = deepcopy(report)
    changed["rows"][0]["review"]["result"]["report"]["requests_this_run"] = 1
    assert not validate(changed)
    changed = deepcopy(report)
    changed["owned_process_stopped"] = False
    assert not validate(changed)


def test_service_gate_rejects_cleanup_error_even_when_report_claims_passed():
    source = Path("docs/phases/phase-05-events-service/evidence/wp03/clean-service-v1.json")
    report = json.loads(source.read_text(encoding="utf-8"))
    assert report["error_category"] == "PermissionError"
    assert not gate().service_passes(report)


def test_ci_gate_rejects_initial_failure_skips_and_changed_sources():
    initial = json.loads(
        Path("docs/phases/phase-05-events-service/evidence/wp03/ci-initial.json").read_text(
            encoding="utf-8"
        )
    )
    validate = gate().ci_passes
    assert not validate(initial)
    report = {
        "status": "passed",
        "test_summary": {"tests": 395, "errors": 0, "failures": 0, "skipped": 0},
        "sources_before": {"source": "one"},
        "sources_after": {"source": "one"},
        "checks": [{"name": n, "returncode": 0} for n in ("lock", "lint", "tests")],
    }
    assert validate(report)
    report["sources_after"]["source"] = "two"
    assert not validate(report)
    report["sources_after"] = report["sources_before"].copy()
    report["test_summary"]["skipped"] = 1
    assert not validate(report)


def test_gate_detects_new_source_and_old_installed_wheel():
    module = gate()
    before = {"src/anlan/a.py": "a", "src/anlan/sql/1.sql": "sql", "tests/t.py": "test"}
    ci = {"sources_after": before}
    service = {
        "interpreter": {
            "package_files": {k: v for k, v in before.items() if k.startswith("src/anlan/")}
        }
    }
    assert module.source_set_matches(ci, before)
    assert not module.source_set_matches(ci, before | {"src/anlan/new.py": "new"})
    assert module.package_matches(ci, service)
    service["interpreter"]["package_files"]["src/anlan/a.py"] = "older-code"
    assert not module.package_matches(ci, service)
