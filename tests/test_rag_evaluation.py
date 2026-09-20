import importlib.util
from pathlib import Path


def runner():
    spec = importlib.util.spec_from_file_location("rag_eval_test", Path("evals/evaluate_rag.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_absent_knowledge_step_is_not_supported_unknown_answer():
    result = runner().score(
        {"results": [], "summary": None, "stop_reason": "model_timeout"},
        {"supporting_doc_ids": [], "fact_reason": None},
    )
    assert result["knowledge_answer_supported"] is False


def test_fact_score_does_not_accept_wrong_fact_values():
    result = runner().score(
        {
            "results": [
                {
                    "tool": "query_worker_qualification",
                    "executed": True,
                    "outcome": "ok",
                    "reason": None,
                    "facts": {"status": "revoked", "qualification_type": "welding"},
                },
                {
                    "tool": "query_area_status",
                    "executed": True,
                    "outcome": "ok",
                    "reason": None,
                    "facts": {"status": "normal"},
                },
            ],
            "summary": None,
            "stop_reason": "model_timeout",
        },
        {"supporting_doc_ids": [], "fact_reason": None},
    )
    assert result["facts_match"] is False
