import importlib.util
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from anlan.common.models import Identity, StrictModel
from anlan.tools.dynamic_mcp.catalog import CatalogEntry, CatalogLease, CatalogSnapshot
from anlan.tools.dynamic_mcp.contracts import CapabilityRequest
from anlan.tools.policy import ToolPolicy
from anlan.tools.registry import ToolDefinition, ToolRegistry

NOW = datetime(2026, 11, 17, tzinfo=UTC)
IDENTITY = Identity(tenant_id="T", user_id="U")
CAPS = ("equipment.asset.query", "equipment.inspection.query", "equipment.fault.query")


def api():
    assert importlib.util.find_spec("anlan.tools.dynamic_mcp.routing"), "routing missing"
    from anlan.tools.dynamic_mcp import routing

    return routing


def entries(tenant="T", factory="F"):
    return tuple(
        CatalogEntry(
            tenant_id=tenant,
            service_id="S",
            config_revision=1,
            generation=1,
            discovery_id="D",
            alias=f"m_{i}",
            original_name=f"device.{i}",
            capability=cap,
            contract_version="1",
            factory_ids=(factory,),
        )
        for i, cap in enumerate(CAPS)
    )


class Service:
    def __init__(self, denied=False):
        self.denied = denied
        self.calls = []

    async def get(self, identity, task_id):
        self.calls.append((identity, task_id))
        if self.denied:
            raise PermissionError("task_denied")
        return {"revision": 3, "correlation_id": "existing-correlation"}


class Registry:
    def __init__(self, items=None):
        self.items = entries() if items is None else items
        self.scopes = []

    async def resolve_business(self, identity, entry):
        return None, CatalogLease(
            tenant_id=entry.tenant_id,
            service_id=entry.service_id,
            generation=entry.generation,
            config_revision=entry.config_revision,
            discovery_id=entry.discovery_id,
            target_policy_version="p1",
            credential_generation="initial",
        )

    async def load_catalog(self, scope):
        self.scopes.append(scope)
        return CatalogSnapshot(
            catalog_id="catalog1",
            tenant_id=scope.identity.tenant_id,
            reader_user_id=scope.identity.user_id,
            entries=self.items,
            created_at=NOW,
        )


def config(r, **updates):
    fields = dict(
        policy_version="p1",
        tenant_id="T",
        factory_directory_version="d1",
        factories={"F": ("二厂",)},
        users={
            "U": r.InquiryUserGrant(factory_ids=("F",), equipment_ids=("E",), capabilities=CAPS)
        },
    )
    fields.update(updates)
    return r.InquiryPolicyConfig(**fields)


def request(r, **updates):
    return r.InquiryRequest(
        **(
            dict(task_id="task", factory_alias="二厂", equipment_id="E", question="设备现状？")
            | updates
        )
    )


@pytest.mark.asyncio
async def test_routes_freezes_host_time_and_grant_from_single_m2_catalog():
    r = api()
    service, registry = Service(), Registry()
    snapshot = await r.prepare_inquiry(service, IDENTITY, request(r), config(r), registry, NOW)
    assert service.calls == [(IDENTITY, "task")]
    assert len(registry.scopes) == 1
    assert registry.scopes[0].capabilities == CAPS
    assert registry.scopes[0].policy_version == "p1"
    assert snapshot.entries == entries()
    assert snapshot.required_capabilities == CAPS
    assert (snapshot.policy_version, snapshot.directory_version, snapshot.catalog_id) == (
        "p1",
        "d1",
        "catalog1",
    )
    assert snapshot.revision == 3 and snapshot.task_id == "task"
    assert snapshot.run_id and snapshot.correlation_id
    assert snapshot.correlation_id == "existing-correlation"
    for entry, (alias, encoded) in zip(snapshot.entries, snapshot.requests, strict=True):
        value = CapabilityRequest.model_validate_json(encoded)
        assert alias == entry.alias and value.capability == entry.capability
        assert value.objects == ["E"] and value.factory_id == "F" and value.queried_at == NOW
    assert snapshot.task_grant.identity == IDENTITY
    assert snapshot.task_grant.grants == snapshot.requests
    with pytest.raises((ValueError, FrozenInstanceError)):
        snapshot.factory_id = "evil"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,error",
    [
        ("unknown", "unknown_factory"),
        ("ambiguous", "ambiguous_factory"),
        ("object", "access_denied"),
        ("user", "access_denied"),
        ("tenant", "access_denied"),
        ("capability", "access_denied"),
        ("factory", "access_denied"),
    ],
)
async def test_denied_routing_never_loads_catalog(case, error):
    r = api()
    policy, req, identity = config(r), request(r), IDENTITY
    if case == "unknown":
        req = request(r, factory_alias="2厂")
    elif case == "ambiguous":
        policy = config(r, factories={"F": ("二厂",), "F2": ("二厂",)})
    elif case == "object":
        req = request(r, equipment_id="OTHER")
    elif case == "user":
        identity = Identity(tenant_id="T", user_id="other")
    elif case == "tenant":
        identity = Identity(tenant_id="OTHER", user_id="U")
    elif case == "capability":
        policy = config(
            r,
            users={
                "U": r.InquiryUserGrant(
                    factory_ids=("F",), equipment_ids=("E",), capabilities=CAPS[:2]
                )
            },
        )
    elif case == "factory":
        policy = config(
            r,
            users={
                "U": r.InquiryUserGrant(
                    factory_ids=("OTHER",), equipment_ids=("E",), capabilities=CAPS
                )
            },
        )
    registry = Registry()
    with pytest.raises(ValueError, match=error):
        await r.prepare_inquiry(Service(), identity, req, policy, registry, NOW)
    assert not registry.scopes


@pytest.mark.asyncio
async def test_task_access_precedes_all_routing():
    r = api()
    registry = Registry()
    with pytest.raises(PermissionError, match="task_denied"):
        await r.prepare_inquiry(Service(True), IDENTITY, request(r), config(r), registry, NOW)
    assert not registry.scopes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,error",
    [
        ("missing", "missing_capability"),
        ("conflict", "source_conflict"),
        ("tenant", "catalog_scope_mismatch"),
        ("factory", "catalog_scope_mismatch"),
        ("alias", "source_conflict"),
    ],
)
async def test_catalog_conflicts_and_out_of_scope_entries_fail_closed(case, error):
    r = api()
    items = entries()
    if case == "missing":
        items = items[:2]
    if case == "conflict":
        items += (items[0].model_copy(update={"alias": "other", "service_id": "S2"}),)
    if case == "alias":
        items = (items[0], items[1].model_copy(update={"alias": items[0].alias}), items[2])
    if case in {"tenant", "factory"}:
        items = entries(**{case: "OTHER"})
    with pytest.raises(ValueError, match=error):
        await r.prepare_inquiry(Service(), IDENTITY, request(r), config(r), Registry(items), NOW)


@pytest.mark.asyncio
async def test_tenant_alias_directory_is_isolated_and_policy_is_deeply_frozen():
    r = api()
    factories, users = (
        {"F": ("二厂",)},
        {"U": r.InquiryUserGrant(factory_ids=("F",), equipment_ids=("E",), capabilities=CAPS)},
    )
    policy = config(r, factories=factories, users=users)
    factories["OTHER"] = ("二厂",)
    users.clear()
    snapshot = await r.prepare_inquiry(Service(), IDENTITY, request(r), policy, Registry(), NOW)
    assert snapshot.factory_id == "F"
    other = config(
        r,
        tenant_id="T2",
        factories={"F2": ("二厂",)},
        users={
            "U": r.InquiryUserGrant(factory_ids=("F2",), equipment_ids=("E2",), capabilities=CAPS)
        },
    )
    result = await r.prepare_inquiry(
        Service(),
        Identity(tenant_id="T2", user_id="U"),
        request(r, equipment_id="E2"),
        other,
        Registry(entries("T2", "F2")),
        NOW,
    )
    assert result.factory_id == "F2" and result.equipment_id == "E2"
    with pytest.raises(TypeError):
        policy.factories["OTHER"] = ("二厂",)


@pytest.mark.asyncio
async def test_naive_host_clock_and_injected_request_identity_rejected():
    r = api()
    with pytest.raises(ValueError):
        request(r, tenant_id="T")
    with pytest.raises(ValueError):
        await r.prepare_inquiry(
            Service(), IDENTITY, request(r), config(r), Registry(), datetime(2026, 11, 17)
        )


def test_task_policy_requires_exact_identity_aliases_and_parameters():
    r = api()
    from anlan.tools.policy import FrozenTaskGrant

    async def handler(identity, args):
        raise AssertionError("not called")

    definition = ToolDefinition(
        "m_0", "device", CapabilityRequest, CapabilityRequest, handler, lambda: NOW
    )
    registry = ToolRegistry([definition])
    args = CapabilityRequest(capability=CAPS[0], factory_id="F", objects=["E"], queried_at=NOW)
    encoded = args.model_dump_json()
    grant = FrozenTaskGrant(IDENTITY, (("m_0", encoded),))
    catalog = ToolPolicy().bind_task_grant(registry, IDENTITY, grant)
    assert catalog.expected("m_0") == json.loads(encoded)
    assert catalog.definitions == (definition,)
    assert r.EQUIPMENT_CAPABILITIES == CAPS
    for bad in (
        None,
        FrozenTaskGrant(Identity(tenant_id="T", user_id="evil"), grant.grants),
        FrozenTaskGrant(IDENTITY, (("unknown", encoded),)),
        FrozenTaskGrant(IDENTITY, grant.grants * 2),
        FrozenTaskGrant(IDENTITY, (("m_0", "{}"),)),
        FrozenTaskGrant(IDENTITY, (("m_0", encoded[:-1] + ',"tenant_id":"T"}'),)),
    ):
        with pytest.raises(ValueError):
            ToolPolicy().bind_task_grant(registry, IDENTITY, bad)
    with pytest.raises(ValueError):
        ToolPolicy().bind_task_grant(
            ToolRegistry([definition, replace(definition, name="extra")]), IDENTITY, grant
        )
    expected = catalog.expected("m_0")
    expected["objects"].append("evil")
    assert catalog.expected("m_0")["objects"] == ["E"]


@pytest.mark.asyncio
async def test_frozen_task_grant_executor_denies_parameter_identity_and_raw_name_tampering():
    api()
    from pydantic import AwareDatetime

    from anlan.tools.executor import ToolExecutor
    from anlan.tools.policy import FrozenTaskGrant

    class Observation(StrictModel):
        tool: str
        object_id: None = None
        queried_at: AwareDatetime

    calls = []

    async def handler(identity, params):
        calls.append((identity, params))
        return Observation(tool="m_0", queried_at=NOW)

    definition = ToolDefinition(
        "m_0", "safe device", CapabilityRequest, Observation, handler, lambda: NOW
    )
    registry = ToolRegistry([definition])
    params = CapabilityRequest(capability=CAPS[0], factory_id="F", objects=["E"], queried_at=NOW)
    mutable = [["m_0", params.model_dump_json()]]
    grant = FrozenTaskGrant(IDENTITY, mutable)
    mutable[0][1] = "{}"
    mutable.clear()
    catalog = ToolPolicy().bind_task_grant(registry, IDENTITY, grant)
    executor = ToolExecutor(catalog)
    raw = params.model_dump(mode="json")
    for update in (
        {"factory_id": "OTHER"},
        {"objects": ["OTHER"]},
        {"capability": CAPS[1]},
        {"queried_at": "2026-11-18T00:00:00Z"},
        {"cursor": "unauthorized-page"},
        {"tenant_id": "evil"},
        {"identity": {"tenant_id": "T", "user_id": "evil"}},
    ):
        result = await executor.execute("m_0", json.dumps(raw | update))
        assert not result["executed"] and not result["evidence_valid"]
    assert not (await executor.execute("device.original", params.model_dump_json()))["executed"]
    assert calls == []
    assert (await executor.execute("m_0", params.model_dump_json()))["evidence_valid"]
    assert len(calls) == 1 and calls[0][0] == IDENTITY


@pytest.mark.parametrize(
    "encoded",
    [
        '{"capability":"equipment.asset.query","capability":"equipment.fault.query"}',
        "null",
        "[]",
        '{"objects":[NaN]}',
    ],
)
def test_binding_rejects_ambiguous_or_nonobject_json(encoded):
    api()
    from anlan.tools.policy import FrozenTaskGrant

    async def handler(identity, params):
        raise AssertionError("not called")

    definition = ToolDefinition(
        "m_0", "device", CapabilityRequest, CapabilityRequest, handler, lambda: NOW
    )
    with pytest.raises(ValueError):
        ToolPolicy().bind_task_grant(
            ToolRegistry([definition]), IDENTITY, FrozenTaskGrant(IDENTITY, (("m_0", encoded),))
        )


@pytest.mark.asyncio
async def test_credential_leases_are_frozen_before_model_catalog_binding():
    from anlan.tools.dynamic_mcp.catalog import CatalogLease

    r = api()
    registry = Registry()
    called = []

    async def resolve(identity, entry):
        called.append(entry.alias)
        return None, CatalogLease(
            tenant_id="T",
            service_id="S",
            generation=1,
            config_revision=1,
            discovery_id="D",
            target_policy_version="p1",
            credential_generation="initial",
        )

    registry.resolve_business = resolve
    snapshot = await r.prepare_inquiry(Service(), IDENTITY, request(r), config(r), registry, NOW)
    assert len(snapshot.leases) == 3
    assert [name for name, _ in snapshot.leases] == called
    assert all(lease.credential_generation == "initial" for _, lease in snapshot.leases)
