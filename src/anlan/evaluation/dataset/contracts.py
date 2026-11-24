"""Versioned dataset authoring contracts, separate from E1 run contracts."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{64}$')]
Fingerprint = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{16}$')]
Texts = list[Text]
NonemptyTexts = Annotated[Texts, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Source(Contract):
    source_id: Text
    path: Text
    sha256: Digest
    logical_document_id: Text
    document_version: Text
    version_pointer: Text
    available_at: AwareDatetime
    origin: Literal['SYNTHETIC']
    derivation: Literal['reworked_seen_asset']


class Evidence(Contract):
    evidence_id: Text
    kind: Literal['fact', 'knowledge']
    source_id: Text
    document_version: Text
    pointer: Text
    quote: Text
    status: Literal['current', 'expired', 'withdrawn', 'unknown']
    observed_at: AwareDatetime
    valid_from: AwareDatetime
    valid_until: AwareDatetime


class Claim(Contract):
    claim: Text
    rationale: Text
    evidence_ids: NonemptyTexts


class ProvisionalLabel(Contract):
    author_kind: Literal['ai', 'human_draft']
    author_id: Text
    status: Literal['provisional']
    claims: Annotated[list[Claim], Field(min_length=1)]


class HumanReview(Contract):
    status: Literal['pending', 'disputed', 'approved']
    reviewer_kind: Literal['human', 'ai'] | None
    reviewer_id: Text | None
    signed_at: AwareDatetime | None
    signature_ref: Text | None
    case_sha256: Digest | None


class Dispute(Contract):
    dispute_id: Text
    claim: Text
    positions: Annotated[Texts, Field(min_length=2)]
    status: Literal['open', 'resolved']
    resolution: Text | None


class Scenario(Contract):
    case_id: Text
    family: Text
    origin: Literal['SYNTHETIC']
    split: Literal['seen_regression']
    slice: Text
    severity: Literal['critical', 'high', 'medium', 'low']
    fixed_at: AwareDatetime
    input: Text
    sources: Annotated[list[Source], Field(min_length=1)]
    required_risks: Texts
    allowed_unknowns: Texts
    required_questions: Texts
    forbidden_claims: NonemptyTexts
    forbidden_actions: NonemptyTexts
    answer_bounds: NonemptyTexts
    blocking_checks: NonemptyTexts
    required_facts: Texts
    required_knowledge: Texts
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    provisional_label: ProvisionalLabel
    human_review: HumanReview
    disputes: list[Dispute]


class SealedDocument(Contract):
    logical_document_id: Text
    document_version: Text
    sha256: Digest


class HoldoutEvent(Contract):
    state: Literal['sealed', 'exposed', 'retired']
    at: AwareDatetime
    reason: Text
    regression_case_id: Text | None


class Holdout(Contract):
    holdout_id: Text
    family: Text
    prompt_fingerprint: Fingerprint
    documents: Annotated[list[SealedDocument], Field(min_length=1)]
    events: Annotated[list[HoldoutEvent], Field(min_length=1)]


class Catalog(Contract):
    schema_version: Literal['anlan-dataset-v2.0']
    dataset_version: Literal['safety-baseline-v2.0']
    rubric_version: Literal['safety-rubric-v2.0']
    cases: Annotated[list[Scenario], Field(min_length=1)]
    sealed_holdouts: list[Holdout]


class ValidationIssue(Contract):
    code: Text
    path: Text


class ValidationResult(Contract):
    valid: bool
    errors: list[ValidationIssue]


class ManifestCase(Contract):
    case_id: Text
    family: Text
    split: Literal['seen_regression']
    case_sha256: Digest
    source_sha256: list[Digest]
    human: Literal['pending'] = 'pending'


class DatasetManifest(Contract):
    schema_version: Literal['anlan-dataset-manifest-v2.0'] = 'anlan-dataset-manifest-v2.0'
    dataset_version: Literal['safety-baseline-v2.0'] = 'safety-baseline-v2.0'
    rubric_version: Literal['safety-rubric-v2.0'] = 'safety-rubric-v2.0'
    catalog_sha256: Digest
    cases: Annotated[list[ManifestCase], Field(min_length=1)]
    sealed_registry_entries: Annotated[int, Field(strict=True, ge=0)]
    quality: Literal['not_evaluated'] = 'not_evaluated'
    model_requests: Literal[0] = 0
