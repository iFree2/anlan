"""Strict candidate registration. These records never grant publication or rights."""
import hashlib
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, field_validator, model_validator

from anlan.knowledge.documents.contracts import Contract, Digest, DocumentIR, Text
from anlan.knowledge.parsing._text_source import TxtIngestError as TxtIngestError
from anlan.knowledge.parsing._text_source import (
    blank_lines,
    line_blocks,
    parser_lineage,
    source_lines,
)


def _source_url(value: str) -> str:
    if any(c.isspace() or ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise ValueError("invalid_candidate_url")
    try:
        parts = urlsplit(value)
        port = parts.port
        valid = (parts.scheme in {"https", "synthetic"} and parts.hostname
                 and parts.username is None and parts.password is None
                 and "\\" not in value and (port is None or 0 < port <= 65535))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("invalid_candidate_url")
    return value


class LicenseEvidence(Contract):
    evidence_url: Text
    observed_at: AwareDatetime
    statement: Text
    evidence_sha256: Digest | None = None

    _url = field_validator("evidence_url")(_source_url)


class SourceCandidate(Contract):
    schema_version: Literal["knowledge.source-candidate.v1"]
    candidate_id: Text
    data_origin: Literal["SYNTHETIC"]
    source_url: Text
    publisher: Text | None = None
    upstream_revision: Text | None = None
    retrieved_at: AwareDatetime | None = None
    license_id: Text | None = None
    license_evidence: LicenseEvidence | None = None
    review_state: Literal["candidate", "needs_review", "rejected"]
    expected_source_sha256: Digest | None = None

    _url = field_validator("source_url")(_source_url)


class TxtIngestMetadata(Contract):
    tenant_id: Text
    logical_document_id: Text
    document_version_id: Text
    generation: int = Field(ge=1)
    title: Text


class TxtIngestDraft(Contract):
    schema_version: Literal["knowledge.txt-draft.v1"]
    raw_bytes: bytes
    filename: Text
    candidate: SourceCandidate
    document: DocumentIR
    omitted_blank_lines: tuple[int, ...]
    review_state: Literal["needs_review"]
    published: Literal[False]

    @field_validator("published", mode="before")
    @classmethod
    def boolean_false_only(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("draft_is_unpublished")
        return value

    @model_validator(mode="after")
    def consistent_source(self):
        lines = source_lines(self.raw_bytes, self.filename,
                             rejected=self.candidate.review_state == "rejected",
                             expected_digest=self.candidate.expected_source_sha256)
        digest = hashlib.sha256(self.raw_bytes).hexdigest()
        if (self.document.source_sha256 != digest or self.document.source_format != "text"
            or self.document.source_uri != f"synthetic://knowledge-v2/txt/{digest}"
            or self.document.blocks != line_blocks(lines)
            or self.omitted_blank_lines != blank_lines(lines)
            or self.document.lineage != parser_lineage()):
            raise ValueError("inconsistent_draft_source")
        return self
