import importlib.util
import sys
from pathlib import Path


def gate():
    sys.path.insert(0, str(Path("evals").resolve()))
    spec = importlib.util.spec_from_file_location("phase04_gate", "evals/phase04_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multi_gate_rejects_missing_roles_and_hidden_requests():
    validate = gate().multi_passes
    report = {
        "status": "completed",
        "mode": "scripted",
        "requests_this_run": 0,
        "budget_before": {},
        "budget_after": {},
        "results": [],
    }
    assert not validate(report)
    import json
    from copy import deepcopy

    actual = json.loads(
        Path("docs/refactoring/evidence/multi-regression.json").read_text(encoding="utf-8")
    )
    assert validate(actual)
    changed = deepcopy(actual)
    changed["results"][1]["evidence"]["children"] = []
    assert not validate(changed)
    changed = deepcopy(actual)
    changed["results"][1]["evidence"]["requests_this_run"] = 1
    assert not validate(changed)
    changed = deepcopy(actual)
    changed["results"][1]["evidence"]["candidate"]["claims"][0]["text"] = "forged"
    assert not validate(changed)


def test_bridge_gate_rejects_incomplete_comparison():
    import json

    validate = gate().bridge_passes
    actual = json.loads(
        Path("docs/refactoring/evidence/java-mcp-regression.json").read_text(encoding="utf-8")
    )
    assert validate(actual)
    actual["cases"][0]["same_evidence"] = False
    assert not validate(actual)
