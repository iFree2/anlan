"""Offline K3a contracts and integration; SYNTHETIC evidence only."""

import importlib
import time
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def api(module="contracts"):
    assert importlib.util.find_spec("anlan.knowledge.retrieval"), "K3a missing"
    return importlib.import_module(f"anlan.knowledge.retrieval.{module}")


def test_contracts_reject_identity_and_loose_parameters():
    c = api()
    for changes in (
        {"tenant_id": "other"},
        {"top_k": "1"},
        {"top_k": True},
        {"top_k": 6},
        {"question": " "},
    ):
        with pytest.raises(ValidationError):
            c.SearchParams(**{"question": "SYNTHETIC", **changes})


def test_contracts_packet_cannot_claim_empty_evidence():
    c = api()
    with pytest.raises(ValidationError):
        c.EvidencePacket(
            operation="search",
            request_id="r",
            requested_at=NOW,
            effective_at=NOW,
            finished_at=NOW,
            catalog_revision="a" * 64,
            status="evidence_found",
            coverage="limited_candidates",
        )


def test_contracts_strict_key_and_unforgeable_cell_provenance():
    c = api()
    with pytest.raises(ValidationError):
        c.EvidenceKey(
            tenant_id="t",
            logical_document_id="d",
            document_version_id="v",
            generation="1",
            block_id="b",
        )
    with pytest.raises(ValidationError):
        c.CellLocation(
            sheet="s", cell="B3", data_row=0, column=1, derivation="verified_original_xlsx"
        )


def synthetic_doc(name="a", tenant="tenant-a", text="SYNTHETIC 监护 condition"):
    from anlan.knowledge.parsing.contracts import SourceCandidate, TxtIngestMetadata
    from anlan.knowledge.parsing.text import parse_txt

    return parse_txt(
        text.encode(),
        filename="sample.txt",
        metadata=TxtIngestMetadata(
            tenant_id=tenant,
            logical_document_id=name,
            document_version_id=f"{name}-v1",
            generation=1,
            title=f"SYNTHETIC {name}",
        ),
        candidate=SourceCandidate(
            schema_version="knowledge.source-candidate.v1",
            candidate_id=name,
            data_origin="SYNTHETIC",
            source_url="synthetic://fixture/txt",
            review_state="candidate",
        ),
    ).document


class Clock:
    def __init__(self):
        self.elapsed = 0.0

    def utc_now(self):
        from datetime import timedelta

        return NOW + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return time.monotonic() + self.elapsed


class Ledger:
    def __init__(self, docs):
        from anlan.knowledge.governance.policy import ACLRecord, ReleaseManifest, WithdrawalRecord

        self.calls = 0
        self.hook = None
        self.records = {}
        for doc in docs:
            key = dict(tenant_id=doc.tenant_id, logical_document_id=doc.logical_document_id)
            self.records[(doc.tenant_id, doc.logical_document_id)] = [
                ACLRecord(
                    **key, revision=1, updated_at=NOW, allowed_users=("reader",), scope=("plant",)
                ),
                WithdrawalRecord(
                    **key, revision=1, updated_at=NOW, withdrawn=False, withdrawn_versions=()
                ),
                ReleaseManifest(
                    **key,
                    document_version_id=doc.document_version_id,
                    generation=doc.generation,
                    source_sha256=doc.source_sha256,
                    ir_sha256=doc.content_digest(),
                    review_status="approved",
                    reviewer="SYNTHETIC fixture only",
                    published_at=NOW,
                    valid_from=NOW,
                    scope=("plant",),
                ),
            ]

    async def read_current(self, *, tenant_id, logical_document_id, checked_at):
        from anlan.knowledge.governance.policy import AuthoritySnapshot

        c = api()
        self.calls += 1
        if self.hook:
            self.hook(self, tenant_id, logical_document_id)
        row = self.records.get((tenant_id, logical_document_id))
        if row is None:
            return c.GovernanceRead()
        return c.GovernanceRead(
            authority=AuthoritySnapshot(checked_at=checked_at, acl=row[0], withdrawal=row[1]),
            manifest=row[2],
        )


def harness(docs=None, *, vector=None, lexical=None):
    docs = (synthetic_doc(),) if docs is None else docs
    assert importlib.util.find_spec("anlan.knowledge.retrieval.catalog"), "K3a catalog missing"
    assert importlib.util.find_spec("anlan.knowledge.retrieval.service"), "K3a service missing"
    catalog = api("catalog").InMemoryCatalog(docs)
    resolver = api("providers").InMemoryBlockResolver(catalog)
    ledger, clock = Ledger(docs), Clock()
    service = api("service").KnowledgeRetrievalService(
        catalog, ledger, resolver, vector, clock, lexical=lexical
    )
    request = api().TrustedRetrievalRequest(
        request_id="synthetic-request",
        tenant_id="tenant-a",
        user_id="reader",
        effective_at=NOW,
        scope=("plant",),
    )
    return service, request, ledger, resolver, clock


def selector(doc):
    return api().ClauseSelector(
        logical_document_id=doc.logical_document_id,
        document_version_id=doc.document_version_id,
        generation=doc.generation,
        block_id=doc.blocks[0].block_id,
    )


@pytest.mark.asyncio
async def test_exact_search_and_get_preserve_raw_ir_and_audit():
    doc = synthetic_doc()
    service, request, ledger, _, _ = harness((doc,))
    packet = await service.search(
        request, api().SearchParams(question="ignored", exact=selector(doc))
    )
    assert packet.status == "evidence_found"
    item = packet.items[0]
    assert item.source_text == doc.blocks[0].source_text
    assert item.ir_sha256 == doc.content_digest() and item.locator == doc.blocks[0].locator
    assert item.generation == doc.generation and item.lineage == doc.lineage
    assert item.checked_at >= packet.requested_at
    assert packet.audit and ledger.calls >= 3
    result = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert result.items[0].source_text == item.source_text


@pytest.mark.asyncio
async def test_exact_wrong_number_and_no_match_are_unknown():
    doc = synthetic_doc()
    service, request, *_ = harness((doc,))
    wrong = api().ClauseSelector(**{**selector(doc).model_dump(), "block_id": "missing"})
    result = await service.get_clause(request, api().ClauseParams(selector=wrong))
    assert result.status == "unknown" and not result.items
    result = await service.search(request, api().SearchParams(question="zzzz_no_match"))
    assert result.status == "unknown" and not result.items


@pytest.mark.asyncio
async def test_search_hybrid_without_vector_is_explicit_incomplete():
    service, request, *_ = harness()
    result = await service.search(request, api().SearchParams(question="监护", mode="hybrid"))
    assert result.status == "incomplete" and result.items
    assert "provider_unavailable" in {i.code for i in result.issues}


def test_contracts_catalog_duplicates_and_limits():
    doc = synthetic_doc()
    assert importlib.util.find_spec("anlan.knowledge.retrieval.catalog"), "K3a catalog missing"
    with pytest.raises(ValueError):
        api("catalog").InMemoryCatalog((doc, doc))
    with pytest.raises(ValueError):
        api("catalog").InMemoryCatalog(tuple(synthetic_doc(str(n)) for n in range(33)))


@pytest.mark.asyncio
async def test_exact_projection_missing_keeps_unknown_not_safe():
    doc = synthetic_doc()
    service, request, _, resolver, _ = harness((doc,))
    resolver.projection.clear()
    result = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert result.status == "unknown" and not result.items
    assert "projection_missing" in {i.code for i in result.issues}


def table_doc(values=("10", "9.9")):
    import json

    from test_knowledge_v2_retrieval_tables import block

    doc = synthetic_doc("table")
    data = json.loads(doc.model_dump_json())
    data["source_format"] = "xlsx"
    data["blocks"] = [block(values).model_dump(mode="json")]
    data["lineage"]["parser"] = "synthetic-structure-fixture"
    return type(doc).model_validate_json(json.dumps(data))


@pytest.mark.asyncio
async def test_table_service_keeps_source_headers_units_footnotes_and_b3():
    doc = table_doc()
    service, request, *_ = harness((doc,))
    packet = await service.query_table(
        request,
        api().TableParams(
            selector=selector(doc),
            filters=(api().CellFilter(column=1, op="ge", value="10", expected_unit="m"),),
        ),
    )
    assert packet.status == "evidence_found" and len(packet.table_rows) == 1
    assert packet.table_rows[0].cells[1].locator.cell == "B3"
    assert packet.items[0].table.headers == doc.blocks[0].table.headers
    assert packet.items[0].table.units == ("", "m") and packet.items[0].table.footnotes
    assert packet.authority_reads >= 3 and packet.projection_reads == 1
    assert packet.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_table_service_without_cell_location_is_unknown():
    doc = synthetic_doc()
    service, request, *_ = harness((doc,))
    packet = await service.query_table(request, api().TableParams(selector=selector(doc)))
    assert packet.status == "unknown" and not packet.table_rows


@pytest.mark.asyncio
async def test_table_byte_trimming_cannot_leave_orphan_rows_or_missing_metadata():
    doc = table_doc(("中" * 12000, "中" * 12000))
    service, request, *_ = harness((doc,))
    packet = await service.query_table(request, api().TableParams(selector=selector(doc)))
    assert len(packet.model_dump_json().encode()) <= 65536
    assert "byte_limited" in {i.code for i in packet.issues}
    tables = {i.key: i for i in packet.items if i.table is not None}
    assert all(row.table_key in tables for row in packet.table_rows)
    assert all(
        tables[row.table_key].table.headers
        and tables[row.table_key].table.units
        and tables[row.table_key].table.footnotes
        for row in packet.table_rows
    )
