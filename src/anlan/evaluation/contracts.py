"""Versioned offline evidence contracts; no model, database or business writes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    model_validator,
)

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Count = Annotated[StrictInt, Field(ge=0)]
Measurement = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
SafetyName = Literal[
    "unauthorized_access",
    "fabricated_facts",
    "automatic_approval",
    "responsibility_assignment",
    "alarm_mutation",
    "unsupported_certainty",
    "invalid_knowledge",
    "stale_revision",
    "alarm_chain_blocked",
]
SAFETY_CHECKS = tuple(SafetyName.__args__)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Manifest(Contract):
    schema_version: Literal["enterprise-eval-v2"]
    code_version: Text
    prompt_version: Text
    model_version: Text
    knowledge_version: Text
    dataset_version: Text
    scorer_version: Literal["enterprise-scorer-v2.0"]
    environment: Text
    run_at: AwareDatetime
    fixed_at: AwareDatetime | None
    request_limit: Count
    request_attempts: Count
    required_case_ids: Annotated[list[Text], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_catalog(self):
        if len(set(self.required_case_ids)) != len(self.required_case_ids):
            raise ValueError("duplicate required case IDs")
        if self.request_attempts > self.request_limit:
            raise ValueError("request attempts exceed limit")
        return self


class Check(Contract):
    status: Literal["pass", "fail", "pending"]
    evidence: Text


class CaseResult(Contract):
    case_id: Text
    origin: Literal["SYNTHETIC", "AUTHORIZED_ENTERPRISE"]
    split: Literal["seen_regression"]
    slice: Text
    severity: Literal["critical", "high", "medium", "low"]
    structure: Check
    semantic: Check
    semantic_source: Literal["deterministic", "judge", "human", "not_measured"]
    human: Check
    human_reviewer: Text | None
    safety: dict[SafetyName, Check]
    errors: list[Text]
    latency_ms: Measurement | None
    cost_usd: Measurement | None
    total_tokens: Count | None
    legacy_issue_set: Check | None = None

    @model_validator(mode="after")
    def validate_review(self):
        if self.human.status != "pending" and not self.human_reviewer:
            raise ValueError("human reviewer is required for a completed review")
        if self.semantic_source == "not_measured" and self.semantic.status != "pending":
            raise ValueError("unmeasured semantics must remain pending")
        if self.semantic_source == "human" and not self.human_reviewer:
            raise ValueError("semantic human reviewer is required")
        return self


class Provenance(Contract):
    adapter: Literal["materials-v1"]
    source_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source_created_at: datetime
    limitation: Text


class Bundle(Contract):
    manifest: Manifest
    cases: list[CaseResult]
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_case_ids(self):
        ids = [row.case_id for row in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case IDs")
        if set(ids) - set(self.manifest.required_case_ids):
            raise ValueError("unexpected case IDs outside frozen manifest")
        return self
