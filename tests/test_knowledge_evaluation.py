import importlib.util
from pathlib import Path


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "knowledge_eval_test", Path("evals/evaluate_knowledge.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_answer_is_not_counted_as_a_supported_quote():
    scores = load_runner().score({"citations": [], "answer": [], "outcome": "unknown"}, [])
    assert scores["quote_fidelity"] is None
    assert scores["answer_support_precision"] is None
    assert scores["unknown_correct"] is True


def test_retrieval_hit_does_not_hide_irrelevant_answer():
    scores = load_runner().score({
        "outcome": "ok", "citations": [
            {"doc_id": "relevant", "chunk_id": "a", "quote": "A"},
            {"doc_id": "irrelevant", "chunk_id": "b", "quote": "B"}],
        "answer": [{"chunk_id": "b", "claim": "B"}],
    }, ["relevant"])
    assert scores["recall_at_k"] == 1
    assert scores["answer_support_precision"] == 0
    assert scores["quote_fidelity"] is True
