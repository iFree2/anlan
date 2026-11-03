"""Strict query boundary and deterministic gateway acceptance."""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from anlan.business_query.contracts import EvidenceBundle, EvidenceCitation, QueryText, QueryType

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


def test_query_contracts_reject_unknown_unbounded_and_partial_evidence():
    for value in ("write", "", 1):
        with pytest.raises(ValidationError):
            TypeAdapter(QueryType).validate_python(value)
    with pytest.raises(ValidationError):
        TypeAdapter(QueryText).validate_python("x" * 501)
    with pytest.raises(ValidationError):
        EvidenceCitation.model_validate({"chunk_id": "c"})
    for revision in (0, -1, None):
        with pytest.raises(ValidationError):
            EvidenceBundle(query_type="application_status", task_id="t",
                           material_revision=revision, application_version=1, observed_at=NOW)
    with pytest.raises(ValidationError):
        EvidenceBundle(query_type="safety_knowledge", observed_at=NOW, private_messages=[])
