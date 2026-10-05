"""A small transfer package must not inherit hot-work decisions or hide unknowns."""

import importlib.util
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / "evals/evaluate_reuse.py"
    assert path.exists(), "Bounded reuse experiment is missing"
    spec = importlib.util.spec_from_file_location("evaluate_reuse", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_transfer_keeps_unknown_even_with_sources_first_preference():
    reuse = module()
    fixture = {"data_origin": "SYNTHETIC", "task_kind": "confined_space_demo"}
    observations = [{"outcome": "unknown", "reason": "not_applicable", "facts": None},
                    {"outcome": "ok", "facts": {"status": "restricted"}}]
    result = reuse.transfer(fixture, observations, {"presentation_order": "sources_first"})
    assert result["unknown_observation_ids"] == ["o1"]
    assert result["observations"][0]["facts"] is None
    assert result["status"] == "requires_human_review"
    assert result["business_rules_reused"] is False
    assert "approval" not in result


@pytest.mark.parametrize("key,value", [("data_origin", "REAL"), ("task_kind", "hot_work")])
def test_wrong_domain_or_real_fixture_is_rejected(key, value):
    reuse = module()
    fixture = {"data_origin": "SYNTHETIC", "task_kind": "confined_space_demo", key: value}
    with pytest.raises(ValueError):
        reuse.transfer(fixture, [], {})
