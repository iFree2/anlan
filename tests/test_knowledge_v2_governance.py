"""Current authorization must dominate historical/rolled-back synthetic IR."""
import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)


def api():
    from anlan import knowledge
    assert importlib.util.find_spec(f"{knowledge.__name__}.governance"), "K1 governance missing"
    return importlib.import_module("anlan.knowledge.governance.policy")


def inputs():
    p = api()
    from anlan.knowledge.documents.contracts import DocumentIR
    doc = DocumentIR.model_validate_json((Path(__file__).parents[1] /
        "examples/synthetic/knowledge-v2/document.json").read_text("utf-8"))
    context = p.AccessContext(tenant_id="tenant-a", user_id="reader", checked_at=NOW,
                              effective_at=NOW, scope=("plant-a", "hot-work"))
    key = {"tenant_id": "tenant-a", "logical_document_id": "synthetic-sop"}
    acl = p.ACLRecord(**key, revision=2, updated_at=NOW,
                      allowed_users=("reader",), scope=("plant-a", "hot-work"))
    withdrawal = p.WithdrawalRecord(**key, revision=3, updated_at=NOW,
                                    withdrawn=False, withdrawn_versions=())
    authority = p.AuthoritySnapshot(checked_at=NOW, acl=acl, withdrawal=withdrawal)
    manifest = p.ReleaseManifest(
        **key, generation=1, document_version_id=doc.document_version_id,
        source_sha256=doc.source_sha256, ir_sha256=doc.content_digest(),
        review_status="approved", reviewer="human-fixture",
        published_at=NOW - timedelta(days=2), valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1), scope=("plant-a", "hot-work"),
    )
    return doc, context, authority, manifest


def replace(model, **changes):
    # model_copy(update=...) bypasses validation; deliberately revalidate instead.
    return type(model).model_validate({**model.model_dump(), **changes})


def decide(doc=None, context=None, authority=None, manifest=None):
    defaults = inputs()
    return api().evaluate_access(doc or defaults[0], context or defaults[1],
                                 authority or defaults[2], manifest or defaults[3])


def test_authorized_current_release():
    result = decide()
    assert result.allowed and result.reason == "allowed"


@pytest.mark.parametrize("changes,reason", [
    ({"tenant_id": "tenant-b"}, "tenant_mismatch"),
    ({"user_id": "intruder"}, "access_denied"),
    ({"scope": ("plant-b", "hot-work")}, "scope_mismatch"),
    ({"scope": ()}, "scope_mismatch"),
    ({"effective_at": NOW + timedelta(days=1)}, "outside_validity"),
    ({"effective_at": NOW - timedelta(days=2)}, "outside_validity"),
    ({"checked_at": NOW + timedelta(seconds=1)}, "authority_not_current"),
])
def test_context_denials(changes, reason):
    doc, context, authority, manifest = inputs()
    result = api().evaluate_access(doc, replace(context, **changes), authority, manifest)
    assert not result.allowed and result.reason == reason


@pytest.mark.parametrize("changes,reason", [
    ({"published_at": None}, "unpublished"),
    ({"published_at": NOW + timedelta(seconds=1)}, "unpublished"),
    ({"review_status": "pending"}, "unreviewed"),
    ({"reviewer": None}, "unreviewed"),
    ({"generation": 2}, "release_mismatch"),
    ({"document_version_id": "different-version"}, "release_mismatch"),
    ({"source_sha256": "c" * 64}, "release_mismatch"),
    ({"scope": ("plant-b",)}, "scope_mismatch"),
])
def test_release_denials(changes, reason):
    doc, context, authority, manifest = inputs()
    result = api().evaluate_access(doc, context, authority, replace(manifest, **changes))
    assert not result.allowed and result.reason == reason


@pytest.mark.parametrize("field", ["acl", "withdrawal"])
def test_missing_authority_record_fails_closed(field):
    doc, context, authority, manifest = inputs()
    result = api().evaluate_access(doc, context, replace(authority, **{field: None}), manifest)
    assert not result.allowed and result.reason == "missing_authority"


@pytest.mark.parametrize("field", ["acl", "withdrawal"])
def test_authority_record_wrong_tenant_or_document(field):
    doc, context, authority, manifest = inputs()
    for key, value in (("tenant_id", "tenant-b"), ("logical_document_id", "other")):
        record = replace(getattr(authority, field), **{key: value})
        updated = replace(authority, **{field: record})
        result = api().evaluate_access(doc, context, updated, manifest)
        assert not result.allowed and result.reason == "authority_mismatch"


@pytest.mark.parametrize("kind", ["acl", "document", "version"])
def test_rollback_and_historical_query_cannot_resurrect_revoked_content(kind):
    doc, context, authority, old_manifest = inputs()
    # Reusing old generation/IR and historical business time never rolls authority back.
    context = replace(context, effective_at=NOW - timedelta(hours=1))
    if kind == "acl":
        authority = replace(authority, acl=replace(authority.acl, allowed_users=()))
    elif kind == "document":
        authority = replace(authority, withdrawal=replace(authority.withdrawal, withdrawn=True))
    else:
        authority = replace(authority, withdrawal=replace(
            authority.withdrawal, withdrawn_versions=(doc.document_version_id,)))
    result = api().evaluate_access(doc, context, authority, old_manifest)
    assert not result.allowed
    assert result.reason == ("access_denied" if kind == "acl" else "withdrawn")


def test_no_snapshot_or_manifest_is_not_permission():
    doc, context, authority, manifest = inputs()
    assert api().evaluate_access(doc, context, None, manifest).reason == "missing_authority"
    assert api().evaluate_access(doc, context, authority, None).reason == "unpublished"


def test_acl_scope_remains_independent_of_release():
    doc, context, authority, manifest = inputs()
    authority = replace(authority, acl=replace(authority.acl, scope=("plant-b",)))
    assert not api().evaluate_access(doc, context, authority, manifest).allowed


def test_governance_contract_is_versioned_and_strict():
    _, _, authority, manifest = inputs()
    assert authority.schema_version == "knowledge.authority.v2"
    assert manifest.schema_version == "knowledge.release.v2"
    for change in ({"generation": "1"}, {"valid_until": manifest.valid_from},
                   {"schema_version": "v1"}, {"admin": True}):
        with pytest.raises(ValidationError):
            replace(manifest, **change)


def test_future_record_is_not_current_authority():
    doc, context, authority, manifest = inputs()
    authority = replace(authority, acl=replace(authority.acl,
                                              updated_at=NOW + timedelta(seconds=1)))
    result = api().evaluate_access(doc, context, authority, manifest)
    assert result.reason == "authority_not_current"


def test_governance_json_round_trip():
    _, _, authority, _ = inputs()
    assert type(authority).model_validate_json(json.dumps(
        json.loads(authority.model_dump_json()))) == authority


def test_partial_applicability_context_is_unknown():
    doc, context, authority, manifest = inputs()
    context = replace(context, scope=("plant-a",))
    result = api().evaluate_access(doc, context, authority, manifest)
    assert not result.allowed and result.reason == "scope_mismatch"


@pytest.mark.parametrize("field", ["source_text", "retrieval_text", "locator", "lineage"])
def test_release_binds_reviewed_ir_not_only_original_asset(field):
    doc, context, authority, manifest = inputs()
    data = json.loads(doc.model_dump_json())
    if field == "lineage":
        data["lineage"]["parser_version"] = "unreviewed-parser"
    elif field == "locator":
        data["blocks"][1]["locator"]["paragraph_id"] = "unreviewed-location"
    else:
        data["blocks"][1][field] = "SYNTHETIC unreviewed content"
    changed = type(doc).model_validate_json(json.dumps(data))
    result = api().evaluate_access(changed, context, authority, manifest)
    assert not result.allowed and result.reason == "release_mismatch"
