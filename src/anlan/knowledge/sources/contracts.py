"""Versioned metadata contracts. License assertions require host evidence review."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                       max_length=2000, strict=True)]
Sha256 = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$', strict=True)]


class Frozen(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class LicenseEvidence(Frozen):
    identifier: Text
    redistribution: Literal['allowed', 'unknown', 'denied']
    evidence_url: Text
    evidence_note: Text

    @field_validator('evidence_url', mode='before')
    @classmethod
    def check_url(cls, value):
        from .validation import validate_url

        return validate_url(value, allow_synthetic=True)


class SourceCandidate(Frozen):
    source_id: Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9-]{0,79}$')]
    publisher: Text
    source_url: Text
    retrieved_at: datetime
    upstream_revision: Text | None
    revision_note: Text
    content_kind: Literal['accident_case', 'dataset_card', 'discovery_page', 'synthetic_case']
    validity: Literal['not_enterprise_authority']
    review_state: Literal['candidate']
    access: Literal['public_web', 'gated_or_unverified', 'offline_fixture']
    data_origin: Literal['public_source', 'project_fixture']
    import_policy: Literal['metadata_only', 'licensed_sample']
    content_sha256: Sha256 | None
    license: LicenseEvidence

    @field_validator('source_url', mode='before')
    @classmethod
    def check_url(cls, value):
        from .validation import validate_url

        return validate_url(value, allow_synthetic=True)

    @model_validator(mode='after')
    def bind_origin_to_uri(self):
        fixture_markers = (self.access == 'offline_fixture',
                           self.content_kind == 'synthetic_case',
                           self.data_origin == 'project_fixture')
        uris = (self.source_url, self.license.evidence_url)
        if any(fixture_markers):
            if not all(fixture_markers) or not all(u.startswith('synthetic://') for u in uris):
                raise ValueError('project fixtures require all fixture markers and synthetic URIs')
        elif any(u.startswith('synthetic://') for u in uris):
            raise ValueError('public sources cannot claim a synthetic URI')
        return self

    @field_validator('retrieved_at')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('retrieved_at requires timezone')
        return value


class SourceManifest(Frozen):
    schema_version: Literal['public-sources-v1']
    manifest_version: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}\.\d+$')]
    sources: Annotated[tuple[SourceCandidate, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode='after')
    def unique_ids(self):
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise ValueError('duplicate source_id')
        return self


class CandidateReceipt(Frozen):
    source_id: str
    upstream_revision: str
    sha256: Sha256
    size_bytes: int
    review_state: Literal['candidate'] = 'candidate'
    validity: Literal['not_enterprise_authority'] = 'not_enterprise_authority'
