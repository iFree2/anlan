"""Real PostgreSQL receipts remain minimal, idempotent and actor scoped."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_events_postgres import dsn, run  # noqa: F401

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity
from anlan.infrastructure.business_queries import BusinessQueryAuditStore, QueryReceipt

pytestmark = pytest.mark.postgres


def test_receipt_is_minimal_idempotent_and_private(dsn):  # noqa: F811
    async def scenario():
        actor = Identity(tenant_id="query-audit-" + uuid4().hex, user_id="applicant")
        store = BusinessQueryAuditStore(dsn)
        await store.initialize()
        receipt = QueryReceipt(source_message_id="message-1", task_id="task-1",
                               query_type="application_status", material_revision=3,
                               application_version=2, outcome="ok")
        first = await store.record(actor, "applicant", receipt)
        assert await store.record(actor, "applicant", receipt) == first
        assert await store.get(actor, "message-1") == first
        assert first["task_id"] == "task-1"
        assert not {"question", "answer", "facts", "citations", "conversation_id"} & first.keys()
        assert first["queried_at"] is not None
        for other in (Identity(tenant_id=actor.tenant_id, user_id="other"),
                      Identity(tenant_id="foreign", user_id=actor.user_id)):
            with pytest.raises(AccessDenied):
                await store.get(other, "message-1")
        with pytest.raises(InvalidTransition):
            await store.record(actor, "applicant", receipt.model_copy(update={"outcome": "error"}))
        await store.initialize()
        assert await store.get(actor, "message-1") == first
    run(scenario())


def test_receipt_rejects_raw_content_and_partial_versions():
    for fields in ({"question": "PRIVATE"}, {"facts": []}, {"task_id": "task-only"},
                   {"citation_ids": ["c"] * 4}, {"query_type": "write"}):
        with pytest.raises(ValidationError):
            QueryReceipt.model_validate({"source_message_id": "m", "query_type": "safety_knowledge",
                                         "outcome": "unknown", **fields})


def test_concurrent_receipts_have_one_identity_scoped_winner(dsn):  # noqa: F811
    async def scenario():
        import asyncio

        actor = Identity(tenant_id="query-race-" + uuid4().hex, user_id="reviewer")
        store = BusinessQueryAuditStore(dsn)
        receipt = QueryReceipt(source_message_id="m", query_type="safety_knowledge",
                               outcome="unknown")
        results = await asyncio.gather(*(store.record(actor, "safety_manager", receipt)
                                         for _ in range(3)))
        assert results[0] == results[1] == results[2]
    run(scenario())
