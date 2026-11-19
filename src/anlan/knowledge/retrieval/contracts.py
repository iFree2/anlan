"""Host-bound requests and versioned evidence; none of these grant publication."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from anlan.knowledge.documents.contracts import (
    Contract,
    Digest,
    DocumentIR,
    Lineage,
    Location,
    Table,
    Text,
)
from anlan.knowledge.governance.policy import AuthoritySnapshot, ReleaseManifest

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class EvidenceKey(Contract):
    tenant_id: Text
    logical_document_id: Text
    document_version_id: Text
    generation: int = Field(ge=1)
    block_id: Text

    @property
    def sort_key(self) -> tuple:
        return (
            self.tenant_id,
            self.logical_document_id,
            self.document_version_id,
            self.generation,
            self.block_id,
        )


def key_for(doc: DocumentIR, block_id: str) -> EvidenceKey:
    return EvidenceKey(
        tenant_id=doc.tenant_id,
        logical_document_id=doc.logical_document_id,
        document_version_id=doc.document_version_id,
        generation=doc.generation,
        block_id=block_id,
    )


class ClauseSelector(Contract):
    logical_document_id: Text
    document_version_id: Text
    generation: int = Field(ge=1)
    block_id: Text


class TrustedRetrievalRequest(Contract):
    request_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    tenant_id: Text
    user_id: Text
    effective_at: AwareDatetime
    scope: tuple[Text, ...]


class SearchParams(Contract):
    question: Question
    exact: ClauseSelector | None = None
    mode: Literal["lexical", "hybrid"] = "lexical"
    top_k: int = Field(default=3, ge=1, le=5)


class ClauseParams(Contract):
    selector: ClauseSelector


class CellFilter(Contract):
    column: int = Field(ge=0, le=99)
    op: Literal["eq", "gt", "ge", "lt", "le"]
    value: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    expected_unit: str | None = None


class TableParams(Contract):
    selector: ClauseSelector
    filters: tuple[CellFilter, ...] = Field(default=(), max_length=8)
    row_limit: int = Field(default=10, ge=1, le=20)


class GovernanceRead(Contract):
    schema_version: Literal["knowledge.governance-read.v1"] = "knowledge.governance-read.v1"
    authority: AuthoritySnapshot | None = None
    manifest: ReleaseManifest | None = None


class CandidateText(Contract):
    key: EvidenceKey
    retrieval_text: Text


class RankedKey(Contract):
    key: EvidenceKey
    score: float = Field(allow_inf_nan=False)


IssueCode = Literal[
    "no_authorized_evidence",
    "applicability_unknown",
    "not_found",
    "projection_missing",
    "dependency_incomplete",
    "provider_unavailable",
    "provider_contract_error",
    "data_error",
    "release_changed",
    "authorization_changed",
    "candidate_truncated",
    "node_limited",
    "byte_limited",
    "deadline_exceeded",
    "authority_budget_exhausted",
    "table_scan_limited",
    "result_limited",
    "unknown_cell_value",
    "physical_cell_location_unavailable",
]


class EvidenceIssue(Contract):
    code: IssueCode
    related_key: EvidenceKey | None = None


class CellLocation(Contract):
    schema_version: Literal["knowledge.table-cell.v1"] = "knowledge.table-cell.v1"
    sheet: Text
    cell: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}[1-9][0-9]*$")]
    data_row: int = Field(ge=0)
    column: int = Field(ge=0)
    derivation: Literal["derived_from_reviewed_ir"] = "derived_from_reviewed_ir"


class TableCell(Contract):
    value: str
    locator: CellLocation


class EvidenceTableRow(Contract):
    table_key: EvidenceKey
    row_index: int = Field(ge=0)
    cells: tuple[TableCell, ...]


class TableSelection(Contract):
    rows: tuple[EvidenceTableRow, ...] = ()
    issues: tuple[EvidenceIssue, ...] = ()
    scanned_rows: int = Field(default=0, ge=0)


class EvidenceItem(Contract):
    key: EvidenceKey
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"
    reference_kind: Literal["synthetic_reference"] = "synthetic_reference"
    title: Text
    source_uri: Text
    source_text: Text
    locator: Location
    source_sha256: Digest
    ir_sha256: Digest
    generation: int = Field(ge=1)
    lineage: Lineage
    checked_at: AwareDatetime
    release_fingerprint: Digest
    acl_revision: int = Field(ge=1)
    withdrawal_revision: int = Field(ge=1)
    dependency_state: Literal["complete", "incomplete"]
    required_keys: tuple[EvidenceKey, ...] = ()
    table: Table | None = None


class AuditEvent(Contract):
    stage: Annotated[str, StringConstraints(max_length=32)]
    decision_code: Annotated[str, StringConstraints(max_length=50)]
    key_digest: Digest | None = None


class EvidencePacket(Contract):
    schema_version: Literal["knowledge.evidence.v2"] = "knowledge.evidence.v2"
    operation: Literal["search", "get_clause", "query_table"]
    request_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    requested_at: AwareDatetime
    effective_at: AwareDatetime
    finished_at: AwareDatetime
    catalog_revision: Digest
    processor_version: Literal["knowledge-retrieval-k3a/1"] = "knowledge-retrieval-k3a/1"
    tokenizer_version: str = "cjk-bigram-asciiword-v1"
    provider_versions: tuple[Text, ...] = ()
    status: Literal["evidence_found", "unknown", "incomplete", "error"]
    coverage: Literal["exact_selection", "limited_candidates", "table_range"]
    items: tuple[EvidenceItem, ...] = ()
    table_rows: tuple[EvidenceTableRow, ...] = ()
    issues: tuple[EvidenceIssue, ...] = ()
    audit: tuple[AuditEvent, ...] = Field(default=(), max_length=128)
    audit_truncated: bool = False
    authority_reads: int = Field(default=0, ge=0, le=128)
    projection_reads: int = Field(default=0, ge=0, le=32)
    elapsed_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def linked_evidence(self):
        keys = {item.key for item in self.items}
        tables = {item.key for item in self.items if item.table is not None}
        if self.status == "evidence_found" and (not self.items or self.issues):
            raise ValueError("evidence_found_requires_complete_nonempty_evidence")
        if any(
            item.dependency_state == "complete" and not set(item.required_keys) <= keys
            for item in self.items
        ):
            raise ValueError("missing_required_evidence")
        if any(row.table_key not in tables for row in self.table_rows):
            raise ValueError("orphan_table_row")
        return self
