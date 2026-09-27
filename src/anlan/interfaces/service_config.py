"""Trusted local configuration, never reconstructed from HTTP request bodies."""

import re
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, SecretStr, field_validator, model_validator

from anlan.common.models import Identity, StrictModel
from anlan.tools.contracts import FactReferences
from anlan.workflows.event_contracts import SourceBinding


class TokenGrant(StrictModel):
    token: SecretStr
    identity: Identity

    @field_validator("token")
    @classmethod
    def valid_token(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", value.get_secret_value()):
            raise ValueError("A bounded, strong local bearer token is required")
        return value


class ConfiguredSource(StrictModel):
    binding: SourceBinding
    references: FactReferences

    @model_validator(mode="after")
    def same_object(self):
        if self.references.area_id != self.binding.object_ref:
            raise ValueError("Source and fact references must name the same object")
        return self


class ServiceConfig(StrictModel):
    schema_version: Literal["local-service-v1"]
    tokens: list[TokenGrant] = Field(min_length=1, max_length=20)
    sources: list[ConfiguredSource] = Field(default_factory=list, max_length=100)
    facts_dir: Path = Path("examples/synthetic/facts-v1")
    embeddings_cache: Path = Path(".runtime/embeddings")
    as_of: AwareDatetime | None = None

    @model_validator(mode="after")
    def unique_scopes(self):
        if len({g.token.get_secret_value() for g in self.tokens}) != len(self.tokens):
            raise ValueError("Tokens must be unique")
        identities = {(g.identity.tenant_id, g.identity.user_id) for g in self.tokens}
        keys = []
        for source in self.sources:
            binding = source.binding
            owner = (binding.identity.tenant_id, binding.identity.user_id)
            if owner not in identities:
                raise ValueError("Source owner has no configured token")
            keys.append((*owner, binding.source_id))
        if len(set(keys)) != len(keys):
            raise ValueError("Ambiguous source binding")
        return self

    @classmethod
    def from_file(cls, path):
        path = Path(path)
        if path.stat().st_size > 262144:
            raise ValueError("Service configuration exceeds limit")
        return cls.model_validate_json(path.read_text(encoding="utf-8-sig"))

    def source(self, identity, source_id):
        return next(
            (
                s
                for s in self.sources
                if s.binding.identity == identity and s.binding.source_id == source_id
            ),
            None,
        )
