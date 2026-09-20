from pathlib import Path

import pytest


def optimized_module(path):
    namespace = {"__name__": "optimized_validation_test", "__file__": str(path.resolve())}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec", optimize=1), namespace)
    return namespace


def test_embedding_gate_validation_survives_python_optimization():
    module = optimized_module(Path("evals/phase02_gate.py"))
    with pytest.raises(ValueError):
        module["check_embedding"]({"artifact_sha256": "wrong"}, {"artifact_sha256": "expected"})


def test_observability_validation_survives_python_optimization():
    module = optimized_module(Path("scripts/smoke_observability.py"))
    with pytest.raises(ValueError):
        module["require"](False, "wrong_parent_span")
