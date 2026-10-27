from datetime import UTC, datetime, timedelta

from anlan.preflight.evaluator import evaluate

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def fact(tool, status, *, outcome="ok", valid_until=None):
    return {
        "tool": tool,
        "outcome": outcome,
        "facts": {"status": status},
        "source": {"valid_until": valid_until or (NOW + timedelta(hours=1))},
    }


def knowledge(*, citations=True, outcome="ok"):
    return {
        "tool": "query_knowledge",
        "outcome": outcome,
        "citations": (
            [{"chunk_id": "citation-1", "valid_until": NOW + timedelta(hours=1)}]
            if citations
            else []
        ),
    }


def test_active_normal_and_current_citation_are_ready_for_human_review():
    result = evaluate(
        fact("query_worker_qualification", "active"),
        fact("query_area_status", "normal"),
        knowledge(),
        NOW,
    )
    assert result.ready is True
    assert result.valid_until == NOW + timedelta(minutes=10)
    assert result.citation_ids == ["citation-1"]


def test_business_exceptions_unknown_expiry_withdrawal_and_no_citation_are_not_ready():
    variants = [
        (
            fact("query_worker_qualification", "suspended"),
            fact("query_area_status", "normal"),
            knowledge(),
        ),
        (
            fact("query_worker_qualification", "active"),
            fact("query_area_status", "restricted"),
            knowledge(),
        ),
        (
            fact("query_worker_qualification", "active", outcome="unknown"),
            fact("query_area_status", "normal"),
            knowledge(),
        ),
        (
            fact("query_worker_qualification", "active", valid_until=NOW),
            fact("query_area_status", "normal"),
            knowledge(),
        ),
        (
            fact("query_worker_qualification", "active"),
            fact("query_area_status", "normal"),
            knowledge(citations=False),
        ),
    ]
    for worker, area, citations in variants:
        assert not evaluate(worker, area, citations, NOW).ready


def test_missing_source_expiry_is_a_gap_not_an_unbounded_ready_result():
    worker = fact("query_worker_qualification", "active")
    worker["source"] = {}
    result = evaluate(worker, fact("query_area_status", "normal"), knowledge(), NOW)
    assert not result.ready
    assert "source_validity_unknown" in result.issues


def test_wrong_query_identity_cannot_be_ready_even_when_status_is_active():
    assert not evaluate(
        fact("unrelated_tool", "active"), fact("query_area_status", "normal"), knowledge(), NOW
    ).ready


def test_not_applicable_reason_cannot_be_erased_by_an_ok_transport_outcome():
    worker = fact("query_worker_qualification", "active")
    worker["reason"] = "not_applicable"
    assert not evaluate(worker, fact("query_area_status", "normal"), knowledge(), NOW).ready
