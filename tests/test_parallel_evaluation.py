import importlib.util
import sys
from pathlib import Path


def evaluator():
    sys.path.insert(0, str(Path("evals").resolve()))
    spec = importlib.util.spec_from_file_location("parallel_eval", "evals/evaluate_parallel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_comparison_requires_complete_same_task_evidence():
    check = evaluator().equivalent
    row = {"snapshot": {"task_id": "same", "revision": 1}, "identity": {"user": "same"},
           "as_of": "same", "question": "same", "memories": [],
           "observations": [{"facts": {"status": "active"}, "elapsed_ms": 1}]}
    assert check(row, {**row, "observations": [{"facts": {"status": "active"},
                                              "elapsed_ms": 9}]})
    assert not check(row, {**row, "observations": [{"facts": {"status": "revoked"}}]})
    assert not check(row, {**row, "snapshot": {"task_id": "other", "revision": 1}})


def test_parallel_live_not_enabled_in_wp01():
    import asyncio
    from types import SimpleNamespace

    import pytest

    from anlan.review_cli import run
    with pytest.raises(ValueError, match="WP01"):
        asyncio.run(run(SimpleNamespace(collection="parallel", mode="deepseek")))
