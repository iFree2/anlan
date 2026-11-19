"""Fail-closed decisions using current authority independently of rollbackable IR.

These are host-only inputs, never model parameters. The host must atomically read
the latest ACL/withdrawal records for each decision (including cache/expansion),
and select the active release manifest. checked_at binds that read to the current
decision; it cannot prove storage freshness or authenticity. Historical business
time does not rewind authorization. This module does not implement publication,
authentication, durable revocation or retrieval.
"""
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from anlan.knowledge.documents.contracts import Contract, Digest, DocumentIR, Text


class DocumentKey(Contract):
    tenant_id: Text
    logical_document_id: Text


class ACLRecord(DocumentKey):
    revision: int = Field(ge=1)
    updated_at: AwareDatetime
    allowed_users: tuple[Text, ...]
    scope: tuple[Text, ...]


class WithdrawalRecord(DocumentKey):
    revision: int = Field(ge=1)
    updated_at: AwareDatetime
    withdrawn: bool
    withdrawn_versions: tuple[Text, ...]


class AuthoritySnapshot(Contract):
    schema_version: Literal["knowledge.authority.v2"] = "knowledge.authority.v2"
    checked_at: AwareDatetime
    acl: ACLRecord | None = None
    withdrawal: WithdrawalRecord | None = None


class AccessContext(Contract):
    tenant_id: Text
    user_id: Text
    checked_at: AwareDatetime
    effective_at: AwareDatetime
    # Exact applicability labels from trusted task context, not inferred by a model.
    # Empty scopes fail closed; this first contract has no wildcard semantics.
    scope: tuple[Text, ...]


class ReleaseManifest(DocumentKey):
    schema_version: Literal["knowledge.release.v2"] = "knowledge.release.v2"
    generation: int = Field(ge=1)
    document_version_id: Text
    source_sha256: Digest
    ir_sha256: Digest
    review_status: Literal["pending", "approved", "rejected"]
    reviewer: Text | None = None
    published_at: AwareDatetime | None = None
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None
    scope: tuple[Text, ...]

    @model_validator(mode="after")
    def validity(self):
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("invalid release validity interval")
        return self


Reason = Literal[
    "allowed", "tenant_mismatch", "missing_authority", "authority_mismatch",
    "authority_not_current", "access_denied", "withdrawn", "unpublished",
    "unreviewed", "release_mismatch", "outside_validity", "scope_mismatch",
]


class AccessDecision(Contract):
    allowed: bool
    reason: Reason


def evaluate_access(
    document: DocumentIR,
    context: AccessContext,
    authority: AuthoritySnapshot | None,
    manifest: ReleaseManifest | None,
) -> AccessDecision:
    """Authorize this document only; callers recheck every expanded dependency.

    A rollback may select an old manifest, but must never roll back authority.
    Absence of a withdrawal record means unknown, never 'not withdrawn'.
    """
    reason = _denial(document, context, authority, manifest)
    return AccessDecision(allowed=reason == "allowed", reason=reason)


def _denial(doc, ctx, authority, manifest) -> Reason:
    if doc.tenant_id != ctx.tenant_id:
        return "tenant_mismatch"
    if authority is None or authority.acl is None or authority.withdrawal is None:
        return "missing_authority"
    records = (authority.acl, authority.withdrawal)
    if any(r.tenant_id != doc.tenant_id or
           r.logical_document_id != doc.logical_document_id for r in records):
        return "authority_mismatch"
    if authority.checked_at != ctx.checked_at or any(
        r.updated_at > ctx.checked_at for r in records
    ):
        return "authority_not_current"
    if ctx.user_id not in authority.acl.allowed_users:
        return "access_denied"
    if authority.withdrawal.withdrawn or (
        doc.document_version_id in authority.withdrawal.withdrawn_versions
    ):
        return "withdrawn"
    if manifest is None:
        return "unpublished"
    if (manifest.tenant_id != doc.tenant_id or
        manifest.logical_document_id != doc.logical_document_id or
        manifest.document_version_id != doc.document_version_id or
        manifest.generation != doc.generation or manifest.source_sha256 != doc.source_sha256 or
        manifest.ir_sha256 != doc.content_digest()):
        return "release_mismatch"
    if manifest.review_status != "approved" or manifest.reviewer is None:
        return "unreviewed"
    if manifest.published_at is None or manifest.published_at > ctx.checked_at:
        return "unpublished"
    if (ctx.effective_at < manifest.valid_from or
        (manifest.valid_until is not None and ctx.effective_at >= manifest.valid_until)):
        return "outside_validity"
    scopes = (ctx.scope, manifest.scope, authority.acl.scope)
    if any(not scope for scope in scopes) or not (
        set(ctx.scope) == set(manifest.scope) and set(ctx.scope) <= set(authority.acl.scope)
    ):
        return "scope_mismatch"
    return "allowed"
