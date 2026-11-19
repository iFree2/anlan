"""Versioned local lexical ranking and validated rank-only fusion."""

import math
import re
from collections import Counter

from anlan.knowledge.retrieval.contracts import CandidateText, EvidenceKey, RankedKey

_TOKENS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[A-Za-z0-9_./-]+")


def tokenize(text: str) -> tuple[str, ...]:
    """cjk-bigram-asciiword-v1; retrieval normalization never edits source text."""
    tokens = []
    for match in _TOKENS.finditer(text):
        word = match.group()
        if word.isascii():
            tokens.append(word.lower())
        elif len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tuple(tokens)


def _checked_route(result: tuple[RankedKey, ...]) -> None:
    seen = set()
    if not isinstance(result, tuple):
        raise ValueError("provider_contract_error")
    for item in result:
        try:
            if not isinstance(item, RankedKey) or not isinstance(item.key, EvidenceKey):
                raise ValueError
            # Recheck raw fields, including nested keys: model_construct can bypass
            # Pydantic's validators and otherwise cause unsafe hashing/errors.
            RankedKey.model_validate({**item.__dict__, "key": dict(item.key.__dict__)})
            if type(item.score) not in (int, float) or not math.isfinite(item.score):
                raise ValueError
            if item.key in seen:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("provider_contract_error") from None
        seen.add(item.key)


def validate_ranked(
    result: tuple[RankedKey, ...], candidates: tuple[CandidateText, ...], limit: int
) -> tuple[RankedKey, ...]:
    """Reject a whole route on contract violations; never clean unauthorized keys."""
    _checked_route(result)
    allowed = {candidate.key for candidate in candidates}
    if len(result) > limit or any(item.key not in allowed for item in result):
        raise ValueError("provider_contract_error")
    return tuple(sorted(result, key=lambda item: (-item.score, item.key.sort_key)))


class LocalBM25:
    version = "bm25-k3a/1"

    async def rank(
        self, question: str, candidates: tuple[CandidateText, ...], limit: int
    ) -> tuple[RankedKey, ...]:
        query = tokenize(question)
        if not query or not candidates or limit <= 0:
            return ()
        documents = [Counter(tokenize(candidate.retrieval_text)) for candidate in candidates]
        lengths = [sum(document.values()) for document in documents]
        average = sum(lengths) / len(documents)
        if not average:
            return ()
        frequencies = Counter(term for document in documents for term in document)
        result = []
        for candidate, document, length in zip(candidates, documents, lengths, strict=True):
            score = 0.0
            for term in query:
                frequency = document[term]
                if frequency:
                    idf = math.log(
                        1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
                    )
                    score += (
                        idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * length / average))
                    )
            if score > 0:
                result.append(RankedKey(key=candidate.key, score=score))
        return tuple(sorted(result, key=lambda item: (-item.score, item.key.sort_key))[:limit])


def rrf(lists: tuple[tuple[RankedKey, ...], ...]) -> tuple[RankedKey, ...]:
    """Fuse 1-based ranks at k=60; provider magnitudes have no role."""
    totals: dict[EvidenceKey, float] = {}
    for route in lists:
        _checked_route(route)
        for rank, item in enumerate(route, 1):
            totals[item.key] = totals.get(item.key, 0.0) + 1 / (60 + rank)
    return tuple(
        RankedKey(key=key, score=score)
        for key, score in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0].sort_key))
    )
