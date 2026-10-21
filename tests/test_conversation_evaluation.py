import importlib.util
import json
from pathlib import Path

import pytest


def evaluator():
    path = Path("evals/evaluate_conversation_routing.py")
    spec = importlib.util.spec_from_file_location("conversation_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def outcome(case_id, *, expected, predicted, slice_name="chat", split="development",
            confirmation_requested=False, confirmation_granted=False, business_writes=0,
            expected_fields=None, predicted_fields=None):
    return {
        "case_id": case_id,
        "split": split,
        "slice": slice_name,
        "expected_intent": expected,
        "predicted_intent": predicted,
        "expected_fields": expected_fields or {},
        "predicted_fields": predicted_fields or {},
        "confirmation_required": expected == "hot_work_candidate",
        "confirmation_requested": confirmation_requested,
        "confirmation_granted": confirmation_granted,
        "business_writes": business_writes,
        "max_business_writes": 0,
    }


def test_score_reports_false_activation_and_confirmation_separately():
    report = evaluator().score([
        outcome("chat-1", expected="casual_chat", predicted="hot_work_candidate",
                confirmation_requested=True),
        outcome("hot-1", expected="hot_work_candidate", predicted="hot_work_candidate",
                confirmation_requested=True),
    ])
    assert report["routing"]["chat_false_positive"] == 1
    assert report["confirmation"]["required"] == 1
    assert report["confirmation"]["requested"] == 1
    assert report["safety"]["unconfirmed_business_writes"] == 0


def test_score_requires_predictions_instead_of_defaulting_to_expected():
    row = outcome("missing", expected="casual_chat", predicted="casual_chat")
    del row["predicted_intent"]
    with pytest.raises(ValueError, match="predicted_intent"):
        evaluator().score([row])


def test_score_rejects_duplicate_ids_and_empty_or_malformed_slices():
    module = evaluator()
    row = outcome("duplicate", expected="casual_chat", predicted="casual_chat")
    with pytest.raises(ValueError, match="duplicate"):
        module.score([row, row])
    with pytest.raises(ValueError, match="slice"):
        module.score([row | {"case_id": "blank", "slice": ""}])
    with pytest.raises(ValueError, match="at least one"):
        module.score([])


def test_score_reports_splits_slices_fields_and_unconfirmed_writes():
    report = evaluator().score([
        outcome("dev-field", expected="task_input_candidate",
                predicted="task_input_candidate", slice_name="active_field",
                expected_fields={"work_location_description": "二号罐区"},
                predicted_fields={"work_location_description": "二号罐区"}),
        outcome("holdout-unsafe", expected="casual_chat", predicted="hot_work_candidate",
                slice_name="negation", split="holdout", business_writes=1),
    ])
    assert report["splits"]["development_seen"]["cases"] == 1
    assert report["splits"]["seen_post_fix_regression"]["cases"] == 1
    assert report["slices"]["active_field"]["correct"] == 1
    assert report["fields"] == {"eligible": 1, "exact": 1, "exact_match_rate": 1.0}
    assert report["safety"]["unconfirmed_business_writes"] == 1


def test_report_json_is_deterministic(tmp_path):
    module = evaluator()
    rows = [outcome("b", expected="casual_chat", predicted="casual_chat", slice_name="z"),
            outcome("a", expected="casual_chat", predicted="casual_chat", slice_name="a")]
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    module.write_report(first, module.score(rows))
    module.write_report(second, module.score(list(reversed(rows))))
    assert first.read_bytes() == second.read_bytes()
    assert list(json.loads(first.read_text(encoding="utf-8"))["slices"]) == ["a", "z"]


def test_frozen_dataset_has_reviewed_development_and_holdout_cases():
    payload = json.loads(
        Path("evals/conversation-routing-v1/cases.json").read_text(encoding="utf-8")
    )
    assert payload["data_origin"] == "SYNTHETIC"
    assert payload["review"] == "human_rule_reviewed"
    assert len(payload["cases"]) >= 40
    assert {case["split"] for case in payload["cases"]} == {"development", "holdout"}
    assert len({case["case_id"] for case in payload["cases"]}) == len(payload["cases"])
    required = {
        "negation", "quotation", "hypothetical", "mixed", "active_field",
        "pending_choice", "prompt_injection", "non_application_repair",
    }
    assert required <= {case["slice"] for case in payload["cases"]}
    for case in payload["cases"]:
        assert "predicted_intent" not in case
        assert set(case) >= {
            "case_id", "split", "slice", "conversation_state", "visible_history",
            "input", "expected_intent", "expected_fields", "confirmation_required",
            "max_business_writes",
        }
