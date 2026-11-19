import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def sample():
    return {
        "schema_version": "dynamic-evidence-v1",
        "capability": "equipment.fault.query",
        "contract_version": "1",
        "data_origin": "SYNTHETIC",
        "objects": ["crane-1"],
        "factory_id": "F002",
        "queried_at": "2026-11-16T08:00:00Z",
        "outcome": "ok",
        "reason": None,
        "data": [],
        "sources": [],
        "complete": False,
        "next_cursor": "page-2",
        "coverage": {
            "object_ids": ["crane-1"],
            "start": "2026-11-16T00:00:00Z",
            "end": "2026-11-17T00:00:00Z",
        },
    }


def test_partial_empty_is_not_usable_and_host_fields_are_separate():
    from anlan.tools.dynamic_mcp.contracts import DynamicEvidence, HostReceipt, ReceivedEvidence

    remote = DynamicEvidence.model_validate(sample())
    assert not remote.usable
    receipt = HostReceipt(
        service_id="equipment",
        tool_name="faults",
        call_id="call-1",
        received_at="2026-11-16T08:00:01Z",
        config_version="v1",
        catalog_version="v1",
        route_version="v1",
        response_sha256="a" * 64,
        selection_reason="configured scope",
    )
    wrapped = ReceivedEvidence(remote=remote, host=receipt)
    assert wrapped.host.service_id == "equipment"
    with pytest.raises(ValidationError):
        DynamicEvidence.model_validate({**sample(), "service_id": "forged"})


@pytest.mark.parametrize(
    "patch",
    [
        {"contract_version": "2"},
        {"capability": "equipment.control"},
        {"queried_at": "2026-11-16"},
        {"complete": True, "next_cursor": "page-2"},
        {"outcome": "error", "reason": None},
        {"objects": []},
        {"data": [{"object_id": "crane-1", "record_id": "fault-1", "status": "safe"}]},
        {"coverage": {"object_ids": ["foreign"], "start": None, "end": None}},
    ],
)
def test_invalid_evidence_is_rejected(patch):
    from anlan.tools.dynamic_mcp.contracts import DynamicEvidence

    with pytest.raises(ValidationError):
        DynamicEvidence.model_validate({**sample(), **patch})


def test_binding_rejects_wrong_request_and_missing_source_stays_unusable():
    from anlan.tools.dynamic_mcp.contracts import CapabilityRequest, DynamicEvidence, bind_evidence

    evidence = DynamicEvidence.model_validate({**sample(), "complete": True, "next_cursor": None})
    request = CapabilityRequest(
        capability=evidence.capability,
        factory_id="F002",
        objects=["other"],
        queried_at=evidence.queried_at,
    )
    with pytest.raises(ValueError, match="binding"):
        bind_evidence(evidence, request)
    assert not evidence.usable


def test_registration_is_declarative_and_three_synthetic_scenarios_validate():
    from anlan.tools.dynamic_mcp.contracts import Registration

    directory = Path("src/anlan/tools/dynamic_mcp/examples")
    configs = [
        Registration.model_validate_json(p.read_text(encoding="utf-8"))
        for p in directory.glob("*.json")
    ]
    assert len(configs) == 3
    assert {b.capability.split(".")[0] for c in configs for b in c.bindings} >= {
        "equipment",
        "contractor",
        "person",
        "permit",
    }
    invalid = configs[0].model_dump(mode="json")
    invalid["connection"]["expression"] = "shell()"
    with pytest.raises(ValidationError):
        Registration.model_validate(invalid)


@pytest.mark.parametrize("change", ["expired_record", "missing_version", "future_source"])
def test_source_and_business_validity_are_independently_required(change):
    from anlan.tools.dynamic_mcp.contracts import DynamicEvidence

    value = {
        **sample(),
        "capability": "equipment.inspection.query",
        "complete": True,
        "next_cursor": None,
        "data": [
            {
                "object_id": "crane-1",
                "record_id": "i-1",
                "original_status": "valid",
                "category": "annual",
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_until": "2026-01-01T00:00:00Z",
                "inspection_at": "2025-01-01T00:00:00Z",
                "status": "valid",
            }
        ],
        "sources": [
            {
                "system_id": "eam",
                "record_id": "i-1",
                "version": "v1",
                "updated_at": "2026-11-15T00:00:00Z",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
            }
        ],
    }
    if change != "expired_record":
        value["data"][0]["valid_until"] = "2027-01-01T00:00:00Z"
    if change == "missing_version":
        value["sources"][0]["version"] = None
    if change == "future_source":
        value["sources"][0]["updated_at"] = "2026-11-17T00:00:00Z"
    assert not DynamicEvidence.model_validate(value).usable


def test_stdio_arguments_require_trusted_exact_profile():
    from anlan.tools.dynamic_mcp.contracts import Registration

    value = json.loads(
        Path("src/anlan/tools/dynamic_mcp/examples/equipment.json").read_text(encoding="utf-8")
    )
    config = Registration.model_validate(value)
    with pytest.raises(ValueError, match="argv"):
        config.validate_targets(
            executable_refs={"synthetic-reference-server"},
            http_targets={},
            stdio_argv={"synthetic-reference-server": ["-c", "evil()"]},
        )


@pytest.mark.parametrize(
    "capability,payload",
    [
        (
            "equipment.asset.query",
            {"name": "起重机", "equipment_type": "crane", "factory_id": "F002", "status": "in_use"},
        ),
        (
            "equipment.inspection.query",
            {
                "category": "annual",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "inspection_at": "2026-01-01T00:00:00Z",
                "status": "valid",
            },
        ),
        ("equipment.fault.query", {"status": "open", "observed_at": "2026-11-15T00:00:00Z"}),
        (
            "contractor.qualification.query",
            {
                "category": "annual",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "status": "active",
            },
        ),
        (
            "person.training.query",
            {
                "category": "annual",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "status": "completed",
                "applicable_factories": ["F002"],
            },
        ),
        (
            "person.access.query",
            {
                "category": "annual",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "status": "granted",
                "factory_id": "F002",
            },
        ),
        (
            "permit.ticket.query",
            {
                "factory_id": "F002",
                "area_id": "area-1",
                "work_type": "hot",
                "start": "2026-11-16T00:00:00Z",
                "end": "2026-11-17T00:00:00Z",
                "revision": "r1",
                "status": "active",
            },
        ),
        (
            "permit.overlap.query",
            {
                "candidate_ticket": "p2",
                "area_id": "area-1",
                "relationship_record_id": "map1",
                "start": "2026-11-16T00:00:00Z",
                "end": "2026-11-17T00:00:00Z",
                "status": "candidate",
            },
        ),
    ],
)
def test_all_eight_capability_payloads_have_sourced_bound_observations(capability, payload):
    from anlan.tools.dynamic_mcp.contracts import CapabilityRequest, DynamicEvidence, bind_evidence

    value = {
        **sample(),
        "capability": capability,
        "complete": True,
        "next_cursor": None,
        "data": [
            {
                "object_id": "crane-1",
                "record_id": "r1",
                "original_status": "企业原始状态",
                **payload,
            }
        ],
        "sources": [
            {
                "system_id": "synthetic",
                "record_id": "r1",
                "version": "v1",
                "updated_at": "2026-11-15T00:00:00Z",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
            }
        ],
    }
    evidence = DynamicEvidence.model_validate(value)
    request = CapabilityRequest(
        capability=capability,
        factory_id="F002",
        objects=["crane-1"],
        queried_at=evidence.queried_at,
        coverage=evidence.coverage,
        category=payload.get("category"),
    )
    assert bind_evidence(evidence, request).usable


def test_training_scope_must_match_evidence_factory():
    from anlan.tools.dynamic_mcp.contracts import DynamicEvidence

    value = {
        **sample(),
        "capability": "person.training.query",
        "data": [
            {
                "object_id": "crane-1",
                "record_id": "r1",
                "original_status": "completed",
                "category": "annual",
                "status": "completed",
                "applicable_factories": ["F001"],
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
            }
        ],
    }
    with pytest.raises(ValidationError, match="factory"):
        DynamicEvidence.model_validate(value)


@pytest.mark.parametrize(
    "start,end",
    [
        ("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"),
        ("2026-11-15T00:00:00Z", "2026-11-16T00:00:00Z"),
        ("2026-11-17T00:00:00Z", "2026-11-18T00:00:00Z"),
    ],
)
@pytest.mark.parametrize("capability", ["permit.ticket.query", "permit.overlap.query"])
def test_permit_records_must_intersect_requested_window(start, end, capability):
    from anlan.tools.dynamic_mcp.contracts import CapabilityRequest, DynamicEvidence, bind_evidence

    record = {
        "object_id": "crane-1",
        "record_id": "r1",
        "original_status": "active",
        "start": start,
        "end": end,
        "area_id": "area-1",
    }
    if capability == "permit.ticket.query":
        record.update(factory_id="F002", work_type="hot", revision="r1", status="active")
    else:
        record.update(candidate_ticket="p2", relationship_record_id="map1", status="candidate")
    value = {**sample(), "capability": capability, "data": [record]}
    request = CapabilityRequest(
        capability=capability,
        factory_id="F002",
        objects=["crane-1"],
        queried_at=value["queried_at"],
        coverage=value["coverage"],
    )
    with pytest.raises(ValueError, match="window"):
        bind_evidence(DynamicEvidence.model_validate(value), request)


def test_fault_observation_cannot_be_after_query_time():
    from anlan.tools.dynamic_mcp.contracts import DynamicEvidence

    value = {
        **sample(),
        "data": [
            {
                "object_id": "crane-1",
                "record_id": "r1",
                "original_status": "open",
                "status": "open",
                "observed_at": "2030-01-01T00:00:00Z",
            }
        ],
    }
    with pytest.raises(ValueError, match="future"):
        DynamicEvidence.model_validate(value)


@pytest.mark.parametrize(
    "model,fields",
    [
        (
            "EvidenceSource",
            {
                "system_id": "eam",
                "record_id": "r1",
                "version": "   ",
                "updated_at": None,
                "valid_from": None,
                "valid_until": None,
            },
        ),
        (
            "HostReceipt",
            {
                "service_id": "eam",
                "tool_name": "faults",
                "call_id": "c1",
                "received_at": "2026-11-16T00:00:00Z",
                "config_version": "v1",
                "catalog_version": "v1",
                "route_version": "v1",
                "response_sha256": "a" * 64,
                "selection_reason": "   ",
            },
        ),
    ],
)
def test_audit_metadata_rejects_whitespace(model, fields):
    from anlan.tools.dynamic_mcp import contracts

    with pytest.raises(ValueError):
        getattr(contracts, model).model_validate(fields)


@pytest.mark.parametrize("capability", ["permit.ticket.query", "permit.overlap.query"])
def test_permit_original_window_may_extend_beyond_query_window(capability):
    from anlan.tools.dynamic_mcp.contracts import CapabilityRequest, DynamicEvidence, bind_evidence

    record = {
        "object_id": "crane-1",
        "record_id": "r1",
        "original_status": "active",
        "start": "2026-11-15T00:00:00Z",
        "end": "2026-11-16T01:00:00Z",
        "area_id": "area-1",
    }
    if capability == "permit.ticket.query":
        record.update(factory_id="F002", work_type="hot", revision="r1", status="active")
    else:
        record.update(candidate_ticket="p2", relationship_record_id="map1", status="candidate")
    value = {**sample(), "capability": capability, "data": [record]}
    request = CapabilityRequest(
        capability=capability,
        factory_id="F002",
        objects=["crane-1"],
        queried_at=value["queried_at"],
        coverage=value["coverage"],
    )
    assert (
        bind_evidence(DynamicEvidence.model_validate(value), request).data[0].start
        < request.coverage.start
    )


def test_registration_preserves_namespaced_original_tool_name():
    from anlan.tools.dynamic_mcp.contracts import Registration

    value = json.loads(
        Path("src/anlan/tools/dynamic_mcp/examples/equipment.json").read_text(encoding="utf-8")
    )
    value["bindings"][0]["tool_name"] = "equipment.asset.query"
    registration = Registration.model_validate(value)
    assert registration.bindings[0].tool_name == "equipment.asset.query"
    for invalid in [" ", " equipment.asset.query", "bad\nname", "bad\x00name"]:
        value["bindings"][0]["tool_name"] = invalid
        with pytest.raises(ValueError):
            Registration.model_validate(value)
