import importlib.util
import json
from dataclasses import replace

import pytest
from test_dynamic_mcp_routing import IDENTITY, NOW, Registry, Service, entries

CAPS = ("contractor.qualification.query", "person.training.query", "person.access.query")


def api():
    assert importlib.util.find_spec("anlan.tools.dynamic_mcp.personnel"), (
        "personnel routing missing"
    )
    from anlan.tools.dynamic_mcp import personnel

    return personnel


def config(p, **updates):
    fields = dict(
        policy_version="p1",
        tenant_id="T",
        directory_version="d1",
        factories={"F": ("二厂",)},
        contractors={"C": p.Contractor(name="承包商", factory_ids=("F",))},
        persons={"P": p.Person(name="张三", contractor_id="C", factory_ids=("F",))},
        users={
            "U": p.PersonnelGrant(
                factory_ids=("F",),
                contractor_ids=("C",),
                person_ids=("P",),
                qualification_categories=("hot-work",),
                training_categories=("safety",),
                capabilities=CAPS,
            )
        },
    )
    fields.update(updates)
    return p.PersonnelPolicy(**fields)


def request(p, **updates):
    return p.PersonnelRequest(
        **(
            dict(
                task_id="task",
                factory_alias="二厂",
                contractor_id="C",
                person_id="P",
                qualification_category="hot-work",
                training_category="safety",
                question="资质培训及准入？",
            )
            | updates
        )
    )


def registry(items=None):
    values = tuple(e.model_copy(update={"capability": c}) for e, c in zip(entries(), CAPS))
    return Registry(values if items is None else items)


@pytest.mark.asyncio
async def test_three_capabilities_bind_distinct_objects_categories_and_leases():
    p = api()
    snapshot = await p.prepare_personnel(
        Service(), IDENTITY, request(p), config(p), registry(), NOW
    )
    values = [json.loads(encoded) for _, encoded in snapshot.requests]
    assert [v["objects"] for v in values] == [["C"], ["P"], ["P"]]
    assert [v["category"] for v in values] == ["hot-work", "safety", None]
    assert snapshot.contractor_id == "C" and snapshot.person_id == "P"
    assert snapshot.required_capabilities == CAPS and len(snapshot.leases) == 3
    assert snapshot.task_grant.grants == snapshot.requests
    assert snapshot.correlation_id == "existing-correlation"
    with pytest.raises(ValueError):
        snapshot.person_id = "OTHER"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,error",
    [
        ("person", "access_denied"),
        ("contractor", "access_denied"),
        ("qualification", "access_denied"),
        ("training", "access_denied"),
        ("relation", "object_relationship_mismatch"),
        ("unknown_factory", "unknown_factory"),
        ("ambiguous_factory", "ambiguous_factory"),
        ("ambiguous_person", "ambiguous_person"),
        ("ambiguous_contractor", "ambiguous_contractor"),
        ("name_mismatch", "object_name_mismatch"),
        ("person_factory", "object_relationship_mismatch"),
        ("tenant", "access_denied"),
    ],
)
async def test_untrusted_or_ambiguous_objects_never_load_catalog(case, error):
    p = api()
    policy, req, identity = config(p), request(p), IDENTITY
    if case in {"person", "contractor"}:
        req = request(p, **{case + "_id": "OTHER"})
    elif case in {"qualification", "training"}:
        req = request(p, **{case + "_category": "OTHER"})
    elif case == "relation":
        policy = config(
            p,
            persons={"P": p.Person(name="张三", contractor_id="OTHER", factory_ids=("F",))},
            contractors={
                "C": p.Contractor(name="承包商", factory_ids=("F",)),
                "OTHER": p.Contractor(name="另一家", factory_ids=("F",)),
            },
        )
    elif case == "person_factory":
        policy = config(
            p, persons={"P": p.Person(name="张三", contractor_id="C", factory_ids=("OTHER",))}
        )
    elif case == "unknown_factory":
        req = request(p, factory_alias="未知厂")
    elif case == "ambiguous_factory":
        policy = config(p, factories={"F": ("二厂",), "F2": ("二厂",)})
    elif case == "ambiguous_person":
        policy = config(
            p,
            persons={
                "P": p.Person(name="张三", contractor_id="C", factory_ids=("F",)),
                "P2": p.Person(name="张三", contractor_id="C", factory_ids=("F",)),
            },
        )
        req = request(p, person_id=None, person_name="张三")
    elif case == "ambiguous_contractor":
        policy = config(
            p,
            contractors={
                "C": p.Contractor(name="承包商", factory_ids=("F",)),
                "C2": p.Contractor(name="承包商", factory_ids=("F",)),
            },
        )
        req = request(p, contractor_id=None, contractor_name="承包商")
    elif case == "name_mismatch":
        req = request(p, person_name="李四")
    elif case == "tenant":
        identity = IDENTITY.model_copy(update={"tenant_id": "OTHER"})
    reg = registry()
    with pytest.raises(ValueError, match=error):
        await p.prepare_personnel(Service(), identity, req, policy, reg, NOW)
    assert not reg.scopes


@pytest.mark.asyncio
async def test_explicit_id_disambiguates_and_policy_deeply_freezes():
    p = api()
    persons = {
        "P": p.Person(name="张三", contractor_id="C", factory_ids=("F",)),
        "P2": p.Person(name="张三", contractor_id="C", factory_ids=("F",)),
    }
    policy = config(p, persons=persons)
    persons.clear()
    snapshot = await p.prepare_personnel(
        Service(), IDENTITY, request(p, person_name="张三"), policy, registry(), NOW
    )
    assert snapshot.person_id == "P"
    with pytest.raises(TypeError):
        policy.persons["X"] = policy.persons["P"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,error",
    [
        ("missing", "missing_capability"),
        ("conflict", "source_conflict"),
        ("scope", "catalog_scope_mismatch"),
        ("alias", "source_conflict"),
        ("lease", "stale_generation"),
    ],
)
async def test_catalog_and_lease_fail_closed(case, error):
    p = api()
    reg = registry()
    if case == "missing":
        reg.items = reg.items[:2]
    if case == "conflict":
        reg.items += (reg.items[0].model_copy(update={"alias": "other", "service_id": "S2"}),)
    if case == "scope":
        reg.items = (reg.items[0].model_copy(update={"tenant_id": "OTHER"}), *reg.items[1:])
    if case == "alias":
        reg.items = (
            reg.items[0],
            reg.items[1].model_copy(update={"alias": reg.items[0].alias}),
            reg.items[2],
        )
    policy = config(p)
    if case == "lease":
        policy = replace(policy, policy_version="p2")
    with pytest.raises(ValueError, match=error):
        await p.prepare_personnel(Service(), IDENTITY, request(p), policy, reg, NOW)


@pytest.mark.asyncio
async def test_task_access_first_and_identity_injection_rejected():
    p = api()
    reg = registry()
    with pytest.raises(PermissionError):
        await p.prepare_personnel(Service(True), IDENTITY, request(p), config(p), reg, NOW)
    assert not reg.scopes
    with pytest.raises(ValueError):
        request(p, tenant_id="T")
    with pytest.raises(ValueError):
        request(p, person_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["person", "contractor", "factory", "capability"])
async def test_existing_valid_objects_require_every_explicit_grant(case):
    p = api()
    policy = config(p)
    grant = policy.users["U"].model_dump()
    grant[
        {
            "person": "person_ids",
            "contractor": "contractor_ids",
            "factory": "factory_ids",
            "capability": "capabilities",
        }[case]
    ] = ()
    policy = replace(policy, users={"U": p.PersonnelGrant(**grant)})
    reg = registry()
    with pytest.raises(ValueError, match="access_denied"):
        await p.prepare_personnel(Service(), IDENTITY, request(p), policy, reg, NOW)
    assert not reg.scopes


@pytest.mark.asyncio
async def test_real_personnel_snapshot_executor_rejects_cross_capability_and_scope_tampering():
    from types import SimpleNamespace

    from anlan.tools.dynamic_mcp.execution import CallBudget, build_dynamic_definitions
    from anlan.tools.executor import ToolExecutor
    from anlan.tools.policy import ToolPolicy

    p = api()
    snapshot = await p.prepare_personnel(
        Service(), IDENTITY, request(p), config(p), registry(), NOW
    )
    called = []

    async def authorize(snap):
        called.append(snap)
        raise AssertionError("unauthorized handler entered")

    budget = CallBudget()
    definitions = build_dynamic_definitions(snapshot, SimpleNamespace(authorize=authorize), budget)
    catalog = ToolPolicy().bind_task_grant(definitions, IDENTITY, snapshot.task_grant)
    executor = ToolExecutor(catalog)
    for alias, encoded in snapshot.requests:
        original = json.loads(encoded)
        for update in (
            {"objects": ["C" if original["objects"] == ["P"] else "P"]},
            {"category": "OTHER"},
            {"capability": CAPS[2] if original["capability"] != CAPS[2] else CAPS[1]},
            {"cursor": "page-2"},
            {"factory_id": "OTHER"},
            {"tenant_id": "OTHER"},
        ):
            observation = await executor.execute(alias, json.dumps(original | update))
            assert not observation["executed"] and not observation["evidence_valid"]
    assert not called and budget.wire_calls == 0
