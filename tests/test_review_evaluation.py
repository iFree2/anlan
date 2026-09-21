import importlib.util
import sys
from pathlib import Path


def scorer():
    sys.path.insert(0, str(Path("evals").resolve()))
    spec = importlib.util.spec_from_file_location("review_evaluator", "evals/evaluate_review.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score


def test_wrong_current_facts_do_not_pass_on_null_reason_alone():
    score = scorer()
    evidence = {"candidate": None, "context": None, "stop_reason": "failed",
                "observations": [{"outcome": "ok", "reason": None, "facts": {"status": "safe"}},
                                 {"outcome": "ok", "reason": None, "facts": {"status": "safe"}}]}
    case = {"fact_reason": None, "supporting_doc_ids": []}
    assert score(evidence, case, False, False)["facts_match"] is False


def test_shared_ledger_delta_is_not_all_attributed_to_this_experiment():
    score_fn = scorer()
    summarize = score_fn.__globals__.get("experiment_attempts")
    assert summarize is not None
    before = {"attempts": [{"attempt_id": "old", "run_id": "past"}]}
    after = {"attempts": [*before["attempts"],
                          {"attempt_id": "own", "run_id": "this-run"},
                          {"attempt_id": "other", "run_id": "other-task"}]}
    own, other = summarize(before, after, {"this-run"})
    assert [a["attempt_id"] for a in own] == ["own"]
    assert [a["attempt_id"] for a in other] == ["other"]
