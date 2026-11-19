"""Trusted host protocols, not remote plugins or publication adapters."""

import time
from datetime import UTC, datetime
from typing import Protocol

from anlan.knowledge.documents.contracts import Block
from anlan.knowledge.retrieval.catalog import InMemoryCatalog
from anlan.knowledge.retrieval.contracts import (
    CandidateText,
    EvidenceKey,
    GovernanceRead,
    RankedKey,
    key_for,
)


class Clock(Protocol):
    def utc_now(self) -> datetime: ...
    def monotonic(self) -> float: ...


class SystemClock:
    def utc_now(self):
        return datetime.now(UTC)

    def monotonic(self):
        return time.monotonic()


class GovernanceSource(Protocol):
    async def read_current(
        self, *, tenant_id: str, logical_document_id: str, checked_at: datetime
    ) -> GovernanceRead: ...


class BlockResolver(Protocol):
    async def resolve(self, key: EvidenceKey) -> Block | None: ...


class RankProvider(Protocol):
    version: str

    async def rank(
        self, question: str, candidates: tuple[CandidateText, ...], limit: int
    ) -> tuple[RankedKey, ...]: ...


class InMemoryBlockResolver:
    """Explicitly mutable projection to exercise missing/corrupt rebuildable content."""

    def __init__(self, catalog: InMemoryCatalog):
        self.projection = {
            key_for(doc, b.block_id): b for doc in catalog.documents for b in doc.blocks
        }

    async def resolve(self, key: EvidenceKey) -> Block | None:
        return self.projection.get(key)


class DeterministicRankProvider:
    """An offline rank fixture, never an embedding model or semantic quality claim."""

    version = "deterministic-rank-fixture/1"

    def __init__(self, order: tuple[EvidenceKey, ...]):
        self.order = order

    async def rank(self, question, candidates, limit):
        allowed = {c.key for c in candidates}
        return tuple(
            RankedKey(key=k, score=1.0 / (n + 1)) for n, k in enumerate(self.order) if k in allowed
        )[:limit]
