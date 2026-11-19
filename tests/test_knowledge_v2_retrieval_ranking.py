"""Offline ranking contracts; scores are rankings, never confidence."""
import importlib
import importlib.util
import math

import pytest

from anlan.knowledge.retrieval.contracts import CandidateText, EvidenceKey, RankedKey


def ranking():
    name = "anlan.knowledge.retrieval.ranking"
    assert importlib.util.find_spec(name) is not None, "ranking implementation missing"
    return importlib.import_module(name)


def key(block="a", **changes):
    return EvidenceKey(tenant_id="t", logical_document_id="d", document_version_id="v",
                       generation=1, block_id=block).model_copy(update=changes)


def candidate(block, text):
    return CandidateText(key=key(block), retrieval_text=text)


def test_tokenizer_chinese_bigrams_ascii_and_unsupported_symbols():
    assert ranking().tokenize("安全作业 火 HOT-Work A/B_1.2 🙂") == (
        "安全", "全作", "作业", "火", "hot-work", "a/b_1.2")
    assert ranking().tokenize("🙂！？") == ()


async def test_bm25_exact_score_stable_ties_and_positive_only():
    engine = ranking().LocalBM25()
    assert engine.version == "bm25-k3a/1"
    candidates = (candidate("b", "fire"), candidate("a", "fire"), candidate("c", "water"))
    result = await engine.rank("fire", candidates, 20)
    assert [item.key.block_id for item in result] == ["a", "b"]
    assert [item.score for item in result] == pytest.approx([math.log(1 + 1.5 / 2.5)] * 2)
    assert await engine.rank("🙂", candidates, 20) == ()
    assert await engine.rank("fire", (), 20) == ()
    assert await engine.rank("fire", candidates, 1) == result[:1]
    assert await engine.rank("missing", candidates, 20) == ()


async def test_bm25_term_frequency_and_length_normalization():
    candidates = (candidate("a", "fire"), candidate("b", "fire fire"))
    result = await ranking().LocalBM25().rank("fire", candidates, 20)
    idf = math.log(1 + .5 / 2.5)
    expected = {"a": idf * 2.5 / (1 + 1.5 * (.25 + .75 / 1.5)),
                "b": idf * 5 / (2 + 1.5 * (.25 + .75 * 2 / 1.5))}
    assert {r.key.block_id: r.score for r in result} == pytest.approx(expected)


@pytest.mark.parametrize("bad", [
    (RankedKey(key=key(), score=1.),) * 2,
    (RankedKey(key=key("unknown"), score=1.),),
    (RankedKey(key=key(tenant_id="other"), score=1.),),
    (RankedKey(key=key(generation=2), score=1.),),
    (RankedKey.model_construct(key=key(), score=float("nan")),),
    (RankedKey.model_construct(key=key(), score=float("inf")),),
    (RankedKey.model_construct(key=key(), score="secret-error"),),
    ({"key": key(), "score": 1.},),
    [RankedKey(key=key(), score=1.)],
])
def test_validate_ranked_rejects_entire_malformed_or_unauthorized_route(bad):
    with pytest.raises(ValueError, match="^provider_contract_error$"):
        ranking().validate_ranked(bad, (candidate("a", "fire"),), 20)


def test_validate_ranked_limits_and_stable_scores():
    candidates = (candidate("a", "fire"), candidate("b", "fire"))
    result = (RankedKey(key=key("b"), score=1.), RankedKey(key=key(), score=1.))
    assert ranking().validate_ranked(result, candidates, 20) == tuple(reversed(result))
    with pytest.raises(ValueError, match="^provider_contract_error$"):
        ranking().validate_ranked(result, candidates, 1)


def test_validate_ranked_rejects_forged_nested_key_without_exception_details():
    bad_key = EvidenceKey.model_construct(tenant_id={"private": "value"},
        logical_document_id="d", document_version_id="v", generation=1, block_id="a")
    with pytest.raises(ValueError, match="^provider_contract_error$"):
        ranking().validate_ranked((RankedKey.model_construct(key=bad_key, score=1.),),
                                  (candidate("a", "fire"),), 20)


def test_validate_ranked_twenty_twenty_one_boundary():
    candidates = tuple(candidate(str(i), "fire") for i in range(21))
    result = tuple(RankedKey(key=c.key, score=1.) for c in candidates)
    assert len(ranking().validate_ranked(result[:20], candidates, 20)) == 20
    with pytest.raises(ValueError, match="^provider_contract_error$"):
        ranking().validate_ranked(result, candidates, 20)


def test_rrf_rank_positions_cross_route_deduplication_and_stable_ties():
    a, b, c = (RankedKey(key=key(x), score=1.) for x in "abc")
    result = ranking().rrf(((a, c), (b, a)))
    assert [r.key.block_id for r in result] == ["a", "b", "c"]
    assert [r.score for r in result] == pytest.approx([1 / 61 + 1 / 62, 1 / 61, 1 / 62])
    assert ranking().rrf(((b,), (c,))) == tuple(sorted(
        ranking().rrf(((c,), (b,))), key=lambda r: (-r.score, r.key.sort_key)))
    assert ranking().rrf(()) == ()
    with pytest.raises(ValueError, match="^provider_contract_error$"):
        ranking().rrf(((a, a),))
