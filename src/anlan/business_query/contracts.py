"""Versioned, bounded evidence; raw records and private messages are forbidden."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from anlan.common.models import NonEmpty, StrictModel

QueryType = Literal["application_status", "application_details", "process_guidance",
                    "safety_knowledge"]
QueryText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True,
                                           min_length=1, max_length=500)]


class EvidenceFact(StrictModel):
    key: NonEmpty
    value: str | int | list[str] | dict[str, str]
    source: Literal["material_checkpoint", "collaboration_application",
                    "collaboration_policy", "knowledge_store"]


class EvidenceCitation(StrictModel):
    chunk_id: NonEmpty
    doc_id: NonEmpty
    version: int = Field(strict=True, ge=1)
    title: NonEmpty
    source: NonEmpty
    quote: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
    content_hash: NonEmpty
    document_hash: NonEmpty
    valid_from: AwareDatetime
    valid_until: AwareDatetime


class EvidenceBundle(StrictModel):
    schema_version: Literal["business-evidence-v1"] = "business-evidence-v1"
    query_type: QueryType
    task_id: NonEmpty | None = None
    material_revision: int | None = Field(default=None, strict=True, ge=1)
    application_version: int | None = Field(default=None, strict=True, ge=1)
    observed_at: AwareDatetime
    facts: list[EvidenceFact] = Field(default_factory=list, max_length=32)
    citations: list[EvidenceCitation] = Field(default_factory=list, max_length=3)
    allowed_actions: list[NonEmpty] = Field(default_factory=list, max_length=12)
    limitations: list[NonEmpty] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def application_versions_move_together(self):
        values = (self.task_id, self.material_revision, self.application_version)
        if self.query_type != "safety_knowledge" and any(v is None for v in values):
            raise ValueError("application queries require task and versions")
        if any(v is not None for v in values) and any(v is None for v in values):
            raise ValueError("task and versions move together")
        return self


class QueryAnswer(StrictModel):
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=12000)]
    evidence: EvidenceBundle | None = None
    requires_selection: bool = False
    candidate_tasks: list[dict[str, str | int]] = Field(default_factory=list, max_length=20)
    outcome: Literal["ok", "unknown", "selection_required", "error"]

    @model_validator(mode="after")
    def cited_knowledge_success(self):
        if (self.outcome == "ok" and self.evidence is not None
                and self.evidence.query_type == "safety_knowledge" and not self.evidence.citations):
            raise ValueError("knowledge answers require citations")
        return self


class CitationReference(StrictModel):
    doc_id: NonEmpty
    chunk_id: NonEmpty
    version: int = Field(strict=True, ge=1)
    content_hash: NonEmpty
    document_hash: NonEmpty
    valid_from: AwareDatetime
    valid_until: AwareDatetime


class QueryReference(StrictModel):
    query_type: QueryType
    task_id: NonEmpty | None = None
    material_revision: int | None = Field(default=None, strict=True, ge=1)
    application_version: int | None = Field(default=None, strict=True, ge=1)
    citations: list[CitationReference] = Field(default_factory=list, max_length=3)
    candidate_task_ids: list[NonEmpty] = Field(default_factory=list, max_length=20)
