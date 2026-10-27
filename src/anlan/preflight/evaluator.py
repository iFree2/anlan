"""Deterministic preflight assessment; query success is never itself approval."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Evaluation:
    ready: bool
    valid_until: datetime
    citation_ids: list[str]
    issues: list[str]


def _until(value):
    source = value.get("source") or {}
    return source.get("valid_until")


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, datetime) and parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def evaluate(worker, area, knowledge, now):
    """Apply the narrow business rules to already-authorized, read-only observations."""
    citations = knowledge.get("citations") or []
    citation_ids = [citation["chunk_id"] for citation in citations if citation.get("chunk_id")]
    worker_ok = (
        worker.get("tool") == "query_worker_qualification"
        and not worker.get("reason")
        and worker.get("outcome") == "ok"
        and (worker.get("facts") or {}).get("status") == "active"
    )
    area_ok = (
        area.get("tool") == "query_area_status"
        and not area.get("reason")
        and area.get("outcome") == "ok"
        and (area.get("facts") or {}).get("status") == "normal"
    )
    knowledge_ok = (
        knowledge.get("tool") == "query_knowledge"
        and not knowledge.get("reason")
        and knowledge.get("outcome") == "ok"
        and bool(citation_ids)
    )
    limits = [now + timedelta(minutes=10)]
    source_known = True
    for observation in (worker, area):
        limit = timestamp(_until(observation))
        if limit is not None:
            limits.append(limit)
        else:
            source_known = False
    for citation in citations:
        if timestamp(citation.get("valid_until")) is not None:
            limits.append(timestamp(citation["valid_until"]))
        else:
            source_known = False
    valid_until = min(limits)
    for observation in (worker, area):
        source = observation.get("source") or {}
        if any(
            timestamp(source.get(name)) is not None and timestamp(source[name]) > now
            for name in ("valid_from", "observed_at")
        ):
            source_known = False
    if any(
        c.get("withdrawn")
        or c.get("current") is False
        or (timestamp(c.get("valid_from")) is not None and timestamp(c["valid_from"]) > now)
        for c in citations
    ):
        source_known = False
    ready = worker_ok and area_ok and knowledge_ok and source_known and valid_until > now
    issues = []
    if not worker_ok:
        issues.append("worker_not_current_active")
    if not area_ok:
        issues.append("area_not_current_normal")
    if not knowledge_ok:
        issues.append("knowledge_citations_missing")
    if valid_until <= now:
        issues.append("evidence_expired")
    if not source_known:
        issues.append("source_validity_unknown")
    return Evaluation(
        ready=ready, valid_until=valid_until, citation_ids=citation_ids, issues=issues
    )
