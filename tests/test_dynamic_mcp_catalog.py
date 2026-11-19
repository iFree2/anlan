"""Pure contract gates: no external business service is contacted."""

import copy
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from anlan.common.models import Identity
from anlan.tools.dynamic_mcp import catalog as c
from anlan.tools.dynamic_mcp.contracts import PAYLOADS, Registration


def registration():
    return Registration.model_validate(
        {
            "schema_version": "dynamic-registration-v1",
            "data_origin": "SYNTHETIC",
            "tenant_id": "tenant",
            "service_id": "service",
            "config_version": "v1",
            "state": "registered",
            "connection": {"transport": "stdio", "executable_ref": "fixture", "argv": []},
            "factories": [{"factory_id": "f1", "aliases": ["Factory"]}],
            "bindings": [
                {
                    "capability": "equipment.asset.query",
                    "contract_version": "1",
                    "tool_name": "asset",
                    "factory_ids": ["f1"],
                }
            ],
        }
    )


def discovery(reg=None):
    reg = reg or registration()
    inp, out = c.expected_schemas(reg.bindings[0].capability)
    return c.make_discovery(
        discovery_id="d1",
        captured_generation=1,
        protocol_version="2025-11-25",
        server_name="fixture",
        server_version="1",
        discovered_at=datetime.now(UTC),
        tools=(c.sanitize_tool("asset", inp, out),),
    )


def test_metadata_removed_without_removing_named_properties():
    schema = {
        "type": "object",
        "title": "SECRET",
        "properties": {"description": {"type": "string", "description": "SECRET"}},
        "additionalProperties": False,
    }
    result = json.loads(c.canonical_schema(schema))
    assert result == {
        "type": "object",
        "properties": {"description": {"type": "string"}},
        "additionalProperties": False,
    }
    assert "SECRET" not in c.canonical_schema(schema)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "unevaluatedProperties": False},
        {"type": "object", "$ref": "https://example.invalid/schema"},
        {"type": "object", "$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"},
        {"type": "object", "$ref": "#/$defs/missing"},
        {"type": "object", "properties": {"x": {"type": "not-a-type"}}},
        {"type": "object", "required": "x"},
    ],
)
def test_unsupported_schema_is_rejected(schema):
    with pytest.raises(ValueError, match="schema_unsupported"):
        c.canonical_schema(schema)


def test_schema_budgets_and_python_cycles():
    schema = {"type": "object"}
    schema["properties"] = {"x": schema}
    with pytest.raises(ValueError):
        c.canonical_schema(schema)
    deep = {"type": "string"}
    for _ in range(20):
        deep = {"type": "array", "items": deep}
    with pytest.raises(ValueError):
        c.canonical_schema(deep)
    with pytest.raises(ValueError):
        c.canonical_schema({"type": "object", "description": "x" * 65536})
    with pytest.raises(ValueError):
        c.canonical_schema(
            {"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(2200)}}
        )


@pytest.mark.parametrize("capability", PAYLOADS)
def test_all_eight_local_contracts_have_fixed_capability_and_version(capability):
    inp, out = c.expected_schemas(capability)
    for schema in (inp, out):
        assert schema["properties"]["capability"] == {"type": "string", "const": capability}
        assert schema["properties"]["contract_version"]["const"] == "1"
        assert json.loads(c.canonical_schema(schema)) == schema


def test_strict_comparison_and_unbound_tools_never_publish():
    reg = registration()
    snap = discovery(reg)
    report = c.validate_discovery(reg, snap)
    assert report.valid and len(report.tools) == 1
    inp, out = c.expected_schemas("equipment.asset.query")
    inp["properties"]["tenant_id"] = {"type": "string"}
    changed = c.make_discovery(
        discovery_id="d2",
        captured_generation=1,
        protocol_version="v",
        server_name="fixture",
        server_version="1",
        discovered_at=datetime.now(UTC),
        tools=(c.sanitize_tool("asset", inp, out),),
    )
    assert c.validate_discovery(reg, changed).error_codes == ("contract_mismatch",)
    missing = c.sanitize_tool("asset", c.expected_schemas("equipment.asset.query")[0])
    assert not c.validate_discovery(reg, snap.model_copy(update={"tools": (missing,)})).valid
    extra = c.sanitize_tool("unbound", {"type": "object"})
    extended = c.make_discovery(**{**snap.model_dump(), "tools": snap.tools + (extra,)})
    assert len(c.validate_discovery(reg, extended).tools) == 1


def test_discovery_is_sanitized_frozen_and_duplicate_names_fail():
    inp, out = c.expected_schemas("equipment.asset.query")
    tool = c.sanitize_tool("asset", inp, out)
    inp["properties"]["capability"]["const"] = "tampered"
    assert "tampered" not in tool.input_schema_json
    assert set(tool.model_dump()) == {"name", "input_schema_json", "output_schema_json"}
    with pytest.raises(ValidationError):
        tool.name = "changed"
    snap = discovery()
    with pytest.raises(ValueError, match="discovery_incomplete"):
        c.make_discovery(**{**snap.model_dump(), "tools": (tool, tool), "digest": None})


def source_and_report():
    reg = registration()
    report = c.validate_discovery(reg, discovery(reg))
    source = c.CatalogSource(
        tenant_id="tenant",
        service_id="service",
        config_revision=1,
        generation=3,
        state="enabled",
        discovery_id="d1",
        validation_digest=report.digest,
        reader_user_ids=("reader",),
        registration_json=reg.model_dump_json(),
        target_policy_version="policy-1",
    )
    return source, report


@pytest.mark.parametrize(
    "tenant,user,caps,factories,count",
    [
        ("tenant", "reader", ("equipment.asset.query",), ("f1",), 1),
        ("other", "reader", ("equipment.asset.query",), ("f1",), 0),
        ("tenant", "other", ("equipment.asset.query",), ("f1",), 0),
        ("tenant", "reader", ("person.access.query",), ("f1",), 0),
        ("tenant", "reader", ("equipment.asset.query",), ("f2",), 0),
    ],
)
def test_catalog_four_way_scope(tenant, user, caps, factories, count):
    source, report = source_and_report()
    scope = c.CatalogScope(
        identity=Identity(tenant_id=tenant, user_id=user),
        capabilities=caps,
        factory_ids=factories,
        policy_version="policy-1",
    )
    catalog = c.build_catalog(scope, (source,), {"d1": report})
    assert len(catalog.entries) == count
    assert isinstance(catalog.entries, tuple)


@pytest.mark.parametrize(
    "change",
    [
        {"state": "disabled"},
        {"reader_user_ids": ()},
        {"discovery_id": "old"},
        {"validation_digest": "0" * 64},
    ],
)
def test_stale_disabled_or_ungranted_heads_are_not_published(change):
    source, report = source_and_report()
    scope = c.CatalogScope(
        identity=Identity(tenant_id="tenant", user_id="reader"),
        capabilities=("equipment.asset.query",),
        factory_ids=("f1",),
        policy_version="policy-1",
    )
    assert not c.build_catalog(scope, (source.model_copy(update=change),), {"d1": report}).entries


def test_alias_is_stable_and_digest_collision_fails_closed(monkeypatch):
    assert c.tool_alias("service", "asset") == c.tool_alias("service", "asset")
    assert c.tool_alias("service", "asset") != c.tool_alias("other", "asset")
    reg = registration()
    data = copy.deepcopy(reg.model_dump())
    data["bindings"].append(
        {
            "capability": "person.access.query",
            "contract_version": "1",
            "tool_name": "access",
            "factory_ids": ["f1"],
        }
    )
    reg = Registration.model_validate(data)
    snap = c.make_discovery(
        **{
            **discovery().model_dump(),
            "tools": discovery().tools
            + (c.sanitize_tool("access", *c.expected_schemas("person.access.query")),),
        }
    )
    monkeypatch.setattr(c, "tool_alias", lambda service, name, **kwargs: "mcp_collision")
    assert c.validate_discovery(reg, snap).error_codes == ("source_conflict",)


def test_alias_uses_full_binding_tuple_and_64_character_digest():
    kwargs = dict(tenant_id="tenant", capability="equipment.asset.query", contract_version="1")
    alias = c.tool_alias("service", "asset", **kwargs)
    assert alias.startswith("m_") and len(alias) == 64
    assert alias != c.tool_alias("service", "asset", **{**kwargs, "tenant_id": "other"})
    assert alias != c.tool_alias(
        "service", "asset", **{**kwargs, "capability": "person.access.query"}
    )


def test_snapshot_digest_is_checked_on_load_and_validation_entry():
    snap = discovery()
    corrupted = snap.model_copy(update={"digest": "f" * 64})
    with pytest.raises(ValueError):
        c.DiscoverySnapshot.model_validate_json(corrupted.model_dump_json())
    assert not c.validate_discovery(registration(), corrupted).valid


def test_catalog_id_is_stable_and_changes_with_policy_or_grant():
    source, report = source_and_report()
    scope = c.CatalogScope(
        identity=Identity(tenant_id="tenant", user_id="reader"),
        capabilities=("equipment.asset.query",),
        factory_ids=("f1",),
        policy_version="policy-1",
    )
    first = c.build_catalog(scope, (source,), {"d1": report})
    second = c.build_catalog(scope, (source,), {"d1": report})
    assert first.catalog_id == second.catalog_id
    assert len(first.catalog_id) == 64
    changed = source.model_copy(update={"reader_user_ids": ("reader", "another")})
    assert c.build_catalog(scope, (changed,), {"d1": report}).catalog_id != first.catalog_id


def test_forged_validation_report_fails_closed():
    source, report = source_and_report()
    scope = c.CatalogScope(
        identity=Identity(tenant_id="tenant", user_id="reader"),
        capabilities=("equipment.asset.query",),
        factory_ids=("f1",),
        policy_version="policy-1",
    )
    forged = report.model_copy(
        update={"tools": (report.tools[0].model_copy(update={"alias": "forged"}),)}
    )
    assert not c.build_catalog(scope, (source,), {"d1": forged}).entries


def test_reference_expansion_depth_is_bounded():
    definitions = {f"d{i}": {"$ref": f"#/$defs/d{i + 1}"} for i in range(20)}
    definitions["d20"] = {"type": "string"}
    with pytest.raises(ValueError, match="schema_unsupported"):
        c.canonical_schema({"type": "object", "$defs": definitions})


@pytest.mark.parametrize(
    "scope_version,head_version", [("current", "retired"), ("", ""), ("current", "")]
)
def test_catalog_rejects_missing_or_retired_policy(scope_version, head_version):
    source, report = source_and_report()
    scope = c.CatalogScope(
        identity=Identity(tenant_id="tenant", user_id="reader"),
        capabilities=("equipment.asset.query",),
        factory_ids=("f1",),
        policy_version=scope_version,
    )
    source = source.model_copy(update={"target_policy_version": head_version})
    assert not c.build_catalog(scope, (source,), {"d1": report}).entries


def test_original_mcp_names_keep_dots_for_bound_and_unbound_tools():
    inp, out = c.expected_schemas("equipment.asset.query")
    tool = c.sanitize_tool("equipment.asset", inp, out)
    unbound = c.sanitize_tool("extensions.metadata", {"type": "object"})
    data = registration().model_dump()
    data["bindings"][0]["tool_name"] = tool.name
    reg = Registration.model_validate(data)
    snapshot = c.make_discovery(
        discovery_id="dot_names",
        captured_generation=1,
        protocol_version="v1",
        server_name="fixture",
        server_version="1",
        discovered_at=datetime.now(UTC),
        tools=(tool, unbound),
    )
    report = c.validate_discovery(reg, snapshot)
    assert report.valid and report.tools[0].original_name == "equipment.asset"
    source = c.CatalogSource(
        tenant_id="tenant",
        service_id="service",
        config_revision=1,
        generation=3,
        state="enabled",
        discovery_id="dot_names",
        validation_digest=report.digest,
        reader_user_ids=("reader",),
        registration_json=reg.model_dump_json(),
        target_policy_version="p1",
    )
    scope = c.CatalogScope(
        identity=Identity(tenant_id="tenant", user_id="reader"),
        capabilities=("equipment.asset.query",),
        factory_ids=("f1",),
        policy_version="p1",
    )
    entries = c.build_catalog(scope, (source,), {"dot_names": report}).entries
    assert len(entries) == 1 and entries[0].original_name == tool.name
