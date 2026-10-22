"""Trusted local configuration, never reconstructed from HTTP request bodies."""

import re
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, SecretStr, field_validator, model_validator

from anlan.collaboration.contracts import Role
from anlan.common.models import Identity, StrictModel
from anlan.tools.contracts import FactReferences
from anlan.workflows.event_contracts import SourceBinding


class TokenGrant(StrictModel):
    token: SecretStr
    identity: Identity
    collaboration_role: Role | None = None

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


class ConsoleProfile(StrictModel):
    """Explicit synthetic console permission; references remain host-controlled."""

    identity: Identity
    references: FactReferences


class ServiceConfig(StrictModel):
    schema_version: Literal["local-service-v1"]
    tokens: list[TokenGrant] = Field(min_length=1, max_length=20)
    sources: list[ConfiguredSource] = Field(default_factory=list, max_length=100)
    facts_dir: Path = Path("examples/synthetic/facts-v1")
    embeddings_cache: Path = Path(".runtime/embeddings")
    as_of: AwareDatetime | None = None
    console_profiles: list[ConsoleProfile] = Field(default_factory=list, max_length=20)
    model_mode: Literal["scripted_double", "deepseek_live"] = "scripted_double"
    console_work_package: Literal["P8-WP04", "P11-WP02"] = "P8-WP04"

    @model_validator(mode="after")
    def unique_scopes(self):
        if len({g.token.get_secret_value() for g in self.tokens}) != len(self.tokens):
            raise ValueError("Tokens must be unique")
        identities = {(g.identity.tenant_id, g.identity.user_id) for g in self.tokens}
        roles = {}
        for grant in self.tokens:
            key = (grant.identity.tenant_id, grant.identity.user_id)
            if key in roles and roles[key] != grant.collaboration_role:
                raise ValueError("Conflicting collaboration roles for the same identity")
            roles[key] = grant.collaboration_role
        keys = []
        for source in self.sources:
            binding = source.binding
            owner = (binding.identity.tenant_id, binding.identity.user_id)
            if owner not in identities:
                raise ValueError("Source owner has no configured token")
            keys.append((*owner, binding.source_id))
        if len(set(keys)) != len(keys):
            raise ValueError("Ambiguous source binding")
        owners = [(p.identity.tenant_id, p.identity.user_id) for p in self.console_profiles]
        if len(set(owners)) != len(owners) or any(owner not in identities for owner in owners):
            raise ValueError("Console profile must have one configured token identity")
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

    def console_profile(self, identity):
        return next((p for p in self.console_profiles if p.identity == identity), None)

    def collaboration_role(self, identity: Identity) -> Role | None:
        return next((g.collaboration_role for g in self.tokens if g.identity == identity), None)

    def collaboration_reviewers(self, identity: Identity) -> list[Identity]:
        """Host-configured same-tenant reviewers, deduplicated without exposing credentials."""
        return sorted(
            {
                g.identity for g in self.tokens
                if g.collaboration_role == "safety_manager"
                and g.identity.tenant_id == identity.tenant_id
                and g.identity.user_id != identity.user_id
            },
            key=lambda reviewer: reviewer.user_id,
        )
