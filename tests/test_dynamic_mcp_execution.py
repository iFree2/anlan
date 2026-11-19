import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from anlan.common.models import Identity
from anlan.tools.dynamic_mcp.catalog import CatalogEntry, CatalogLease
from anlan.tools.dynamic_mcp.contracts import CapabilityRequest, Registration
from anlan.tools.dynamic_mcp.runtime import ExecutableProfile, TrustedTargets


def api():
    assert importlib.util.find_spec("anlan.tools.dynamic_mcp.execution"), "execution missing"
    from anlan.tools.dynamic_mcp import execution

    return execution


def test_attempt_and_wire_limits_are_independent_and_hard():
    e = api()
    budget = e.CallBudget()
    for _ in range(6):
        budget.reserve_attempt()
    assert budget.attempts == 6
    assert budget.wire_calls == 0
    with pytest.raises(e.RuntimeFailure, match="tool_budget_exhausted"):
        budget.reserve_attempt()
    for _ in range(6):
        budget.reserve_wire_call()
    with pytest.raises(e.RuntimeFailure, match="tool_budget_exhausted"):
        budget.reserve_wire_call()
    assert budget.wire_calls == 6


def test_budget_deadline_is_monotonic():
    e = api()
    budget = e.CallBudget(deadline=0)
    with pytest.raises(e.RuntimeFailure, match="timeout"):
        budget.reserve_wire_call()
    assert budget.wire_calls == 0


class BusinessRegistry:
    current = True

    async def resolve_business(self, identity, entry):
        if not self.current:
            raise ValueError("stale_generation")
        return self.registration, self.lease

    async def assert_current(self, lease):
        if not self.current:
            raise ValueError("stale_generation")


class Audit:
    def __init__(self):
        self.receipts = []
        self.records = []

    async def publish(self, identity, lease, receipt, **metadata):
        self.receipts.append(receipt)
        self.records.append(metadata)


def harness(tmp_path, mode="normal"):
    e = api()
    fixture = str(Path("tests/fixtures/dynamic_mcp_equipment_server.py").resolve())
    log = tmp_path / "wire.jsonl"
    argv = (fixture, mode, str(log))
    identity = Identity(tenant_id="tenant", user_id="reader")
    registry = BusinessRegistry()
    registry.registration = Registration(
        schema_version="dynamic-registration-v1",
        data_origin="SYNTHETIC",
        tenant_id="tenant",
        service_id="service",
        config_version="v1",
        state="enabled",
        connection=dict(transport="stdio", executable_ref="fixture", argv=list(argv)),
        factories=[dict(factory_id="F001", aliases=["factory"])],
        bindings=[
            dict(capability=cap, contract_version="1", tool_name=cap, factory_ids=["F001"])
            for cap in (
                "equipment.asset.query",
                "equipment.inspection.query",
                "equipment.fault.query",
            )
        ],
    )
    registry.lease = CatalogLease(
        tenant_id="tenant",
        service_id="service",
        generation=4,
        config_revision=1,
        discovery_id="discovery",
        target_policy_version="p1",
        credential_generation="",
    )
    entries = tuple(
        CatalogEntry(
            tenant_id="tenant",
            service_id="service",
            config_revision=1,
            generation=4,
            discovery_id="discovery",
            alias="m_" + str(i),
            original_name=cap,
            capability=cap,
            contract_version="1",
            factory_ids=("F001",),
        )
        for i, cap in enumerate(
            ("equipment.asset.query", "equipment.inspection.query", "equipment.fault.query")
        )
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    requests = tuple(
        (
            entry.alias,
            CapabilityRequest(
                capability=entry.capability, factory_id="F001", objects=["E001"], queried_at=now
            ).model_dump_json(),
        )
        for entry in entries
    )
    snapshot = SimpleNamespace(
        leases=tuple((entry.alias, registry.lease) for entry in entries),
        identity=identity,
        query_at=now,
        entries=entries,
        requests=requests,
        catalog_id="catalog",
        policy_version="p1",
        directory_version="d1",
        task_id="task",
        run_id="run",
        correlation_id="correlation",
        revision=1,
    )
    targets = TrustedTargets(
        "p1", (ExecutableProfile("tenant", "fixture", sys.executable, argv, str(Path.cwd())),)
    )
    audit = Audit()
    host = e.ExecutionHost(registry, targets, None, audit, lambda snapshot: True)
    budget = e.CallBudget()
    return e, snapshot, host, budget, log, audit


async def test_three_real_sdk_calls_bind_receipts_and_fixed_clock(tmp_path):
    e, snapshot, host, budget, log, audit = harness(tmp_path)
    assert hasattr(e, "build_dynamic_definitions"), "bound definitions missing"
    definitions = e.build_dynamic_definitions(snapshot, host, budget)
    for definition in definitions.definitions:
        params = json.loads(dict(snapshot.requests)[definition.name])
        value = await definition.handler(snapshot.identity, params)
        assert value.evidence.remote.capability == value.required_capability
        assert value.evidence.host.received_at > snapshot.query_at
        assert value.queried_at == definition.clock() == snapshot.query_at
        assert value.evidence.remote.usable
    assert budget.wire_calls == len(audit.receipts) == 3
    wire = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum(item.get("method") == "tools/call" for item in wire) == 3


@pytest.mark.parametrize("mode", ["wrong_time", "partial"])
async def test_wrong_time_rejected_partial_preserved(tmp_path, mode):
    e, snapshot, host, budget, log, audit = harness(tmp_path, mode)
    assert hasattr(e, "build_dynamic_definitions"), "bound definitions missing"
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    params = json.loads(dict(snapshot.requests)[definition.name])
    if mode == "wrong_time":
        with pytest.raises(ValueError):
            await definition.handler(snapshot.identity, params)
        assert audit.records[0]["error_code"] == "data_error"
        assert audit.records[0]["evidence_valid"] is False
    else:
        value = await definition.handler(snapshot.identity, params)
        assert value.complete is False
        assert not value.evidence.remote.usable
        assert value.evidence.remote.next_cursor == "next-page"


async def test_changed_identity_parameters_and_disabled_are_zero_wire(tmp_path):
    e, snapshot, host, budget, log, audit = harness(tmp_path)
    assert hasattr(e, "build_dynamic_definitions"), "bound definitions missing"
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    params = json.loads(dict(snapshot.requests)[definition.name])
    for identity, arguments in [
        (Identity(tenant_id="other", user_id="reader"), params),
        (snapshot.identity, {**params, "objects": ["E999"]}),
    ]:
        with pytest.raises((ValueError, e.RuntimeFailure)):
            await definition.handler(identity, arguments)
    host.registry.current = False
    with pytest.raises((ValueError, e.RuntimeFailure)):
        await definition.handler(snapshot.identity, params)
    assert budget.wire_calls == 0
    assert not log.exists()


def test_pg_business_resolve_and_publish_disable_serialization():
    from test_dynamic_mcp_registry import discovered, run, setup

    from anlan.tools.dynamic_mcp.catalog import CatalogScope
    from anlan.tools.dynamic_mcp.contracts import HostReceipt

    async def scenario():
        e = api()
        assert hasattr(e, "InquiryAuditStore"), "independent audit missing"
        r, registry, admin, tenant = setup()
        await registry.initialize(admin)
        head = await discovered(registry, r, admin, tenant, "service")
        await registry.enable(admin, tenant, "service", 2, head["validation_digest"], "enable")
        identity = Identity(tenant_id=tenant, user_id="reader")
        catalog = await registry.load_catalog(
            CatalogScope(
                identity=identity,
                capabilities=("equipment.asset.query",),
                factory_ids=("F001",),
                policy_version="p1",
            )
        )
        assert len(catalog.entries) == 1
        entry = catalog.entries[0]
        registration, lease = await registry.resolve_business(identity, entry)
        assert registration.tenant_id == tenant
        for bad_identity in (
            Identity(tenant_id="other", user_id="reader"),
            Identity(tenant_id=tenant, user_id="intruder"),
        ):
            with pytest.raises(r.RegistryError, match="access_denied"):
                await registry.resolve_business(bad_identity, entry)
        audit = e.InquiryAuditStore(registry)
        await audit.initialize(admin)
        await audit.initialize(admin)
        receipt = HostReceipt(
            service_id="service",
            tool_name=entry.original_name,
            call_id="call-1",
            received_at=datetime.now(timezone.utc),
            config_version="v1",
            catalog_version=catalog.catalog_id,
            route_version="d1",
            response_sha256="a" * 64,
            selection_reason="single_authorized_source",
        )
        await audit.publish(
            identity,
            lease,
            receipt,
            alias=entry.alias,
            capability=entry.capability,
            task_id="task",
            run_id="run",
            correlation_id="corr",
            elapsed_ms=1,
        )
        await registry.disable(admin, tenant, "service", lease.generation, "disable")
        with pytest.raises(r.RegistryError, match="stale_generation"):
            await audit.publish(
                identity,
                lease,
                receipt.model_copy(update={"call_id": "call-2"}),
                alias=entry.alias,
                capability=entry.capability,
                task_id="task",
                run_id="run",
                correlation_id="corr",
                elapsed_ms=1,
            )
        async with registry._connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT call_id FROM anlan_v2.dynamic_mcp_calls WHERE tenant_id=%s", (tenant,)
                )
            ).fetchall()
        assert [row["call_id"] for row in rows] == ["call-1"]

    run(scenario())


@pytest.mark.parametrize("authorization", [None, 0, "", False])
async def test_authorization_requires_explicit_allow(tmp_path, authorization):
    from dataclasses import replace

    e, snapshot, host, budget, log, audit = harness(tmp_path)
    host = replace(host, authorize=lambda snapshot: authorization)
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    with pytest.raises(e.RuntimeFailure, match="access_denied"):
        await definition.handler(
            snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
        )
    assert not log.exists()


async def test_cancel_sends_actual_call_wire_id_and_does_not_publish(tmp_path):
    import asyncio

    e, snapshot, host, budget, log, audit = harness(tmp_path, "slow")
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    task = asyncio.create_task(
        definition.handler(snapshot.identity, json.loads(dict(snapshot.requests)[definition.name]))
    )
    for _ in range(200):
        if log.exists() and "tools/call" in log.read_text():
            break
        await asyncio.sleep(0.025)
    else:
        pytest.fail("no SDK business call observed")
    from time import monotonic

    from test_dynamic_mcp_runtime import pid_exited

    cancelled_at = monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cleanup_seconds = monotonic() - cancelled_at
    assert cleanup_seconds < 4
    print(f"cancel_cleanup_seconds={cleanup_seconds:.3f}")
    wire = [json.loads(line) for line in log.read_text().splitlines()]
    call_id = next(item["request_id"] for item in wire if item.get("method") == "tools/call")
    assert any(item.get("cancelled_id") == call_id for item in wire)
    assert pid_exited(wire[0]["pid"])
    assert not audit.receipts


async def test_frozen_credential_lease_change_is_zero_wire(tmp_path):
    e, snapshot, host, budget, log, audit = harness(tmp_path)
    snapshot.leases = tuple((entry.alias, host.registry.lease) for entry in snapshot.entries)
    host.registry.lease = host.registry.lease.model_copy(update={"credential_generation": "new"})
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    with pytest.raises(e.RuntimeFailure, match="stale_generation"):
        await definition.handler(
            snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
        )
    assert not log.exists()
    assert budget.wire_calls == 0


def test_pg_publish_share_lock_orders_disable_and_rechecks_guard():
    import asyncio

    from test_dynamic_mcp_registry import discovered, run, setup

    from anlan.tools.dynamic_mcp.catalog import CatalogScope
    from anlan.tools.dynamic_mcp.contracts import HostReceipt

    async def scenario():
        e = api()
        r, registry, admin, tenant = setup()
        await registry.initialize(admin)
        head = await discovered(registry, r, admin, tenant, "service")
        await registry.enable(admin, tenant, "service", 2, head["validation_digest"], "enable")
        identity = Identity(tenant_id=tenant, user_id="reader")
        catalog = await registry.load_catalog(
            CatalogScope(
                identity=identity,
                capabilities=("equipment.asset.query",),
                factory_ids=("F001",),
                policy_version="p1",
            )
        )
        entry = catalog.entries[0]
        _, lease = await registry.resolve_business(identity, entry)
        audit = e.InquiryAuditStore(registry)
        await audit.initialize(admin)
        receipt = HostReceipt(
            service_id="service",
            tool_name=entry.original_name,
            call_id="ordered-call",
            received_at=datetime.now(timezone.utc),
            config_version="v1",
            catalog_version=catalog.catalog_id,
            route_version="d1",
            response_sha256="b" * 64,
            selection_reason="single_authorized_source",
        )
        entered, release = asyncio.Event(), asyncio.Event()

        async def guard():
            entered.set()
            await release.wait()

        publishing = asyncio.create_task(
            audit.publish(
                identity,
                lease,
                receipt,
                alias=entry.alias,
                capability=entry.capability,
                task_id="task",
                run_id="run",
                correlation_id="corr",
                elapsed_ms=1,
                guard=guard,
            )
        )
        # A missing API fails here instead of leaving an unbounded event wait.
        done, _ = await asyncio.wait(
            (publishing, asyncio.create_task(entered.wait())),
            return_when=asyncio.FIRST_COMPLETED,
            timeout=2,
        )
        if publishing in done:
            await publishing
        assert entered.is_set()
        disabling = asyncio.create_task(
            registry.disable(admin, tenant, "service", lease.generation, "disable")
        )
        await asyncio.sleep(0.05)
        assert not disabling.done(), "disable must wait for publication SHARE lock"
        release.set()
        await publishing
        await disabling
        with pytest.raises(r.RegistryError, match="stale_generation"):
            await registry.assert_current(lease)

    run(scenario())


@pytest.mark.parametrize("mode", ["wrong_object", "wrong_capability", "oversized", "is_error"])
async def test_sdk_invalid_business_result_cannot_be_published(tmp_path, mode):
    e, snapshot, host, budget, log, audit = harness(tmp_path, mode)
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    with pytest.raises((ValueError, e.RuntimeFailure)):
        await definition.handler(
            snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
        )
    assert budget.wire_calls == 1
    assert audit.records[0]["error_code"] in {"data_error", "oversized_result"}
    assert audit.records[0]["evidence_valid"] is False

    if mode == "wrong_capability":
        # SDK rejects schema before returning content to the host.
        assert audit.records[0]["response_hash_available"] is False


async def test_live_schema_drift_is_zero_business_wire(tmp_path):
    e, snapshot, host, budget, log, audit = harness(tmp_path, "stale_schema")
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    with pytest.raises(e.RuntimeFailure, match="stale_schema"):
        await definition.handler(
            snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
        )
    assert budget.wire_calls == 0
    assert not audit.receipts


@pytest.mark.parametrize("mode", ["missing_source", "partial_empty"])
async def test_unsourced_or_partial_empty_never_becomes_usable(tmp_path, mode):
    e, snapshot, host, budget, log, audit = harness(tmp_path, mode)
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[2]
    value = await definition.handler(
        snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
    )
    assert not value.evidence.remote.usable
    if mode == "partial_empty":
        assert value.evidence.remote.data == []
        assert value.complete is False
        assert value.evidence.remote.next_cursor == "next-page"


async def test_disconnected_preserves_fixed_observation_reason(tmp_path):
    from anlan.tools.executor import ToolExecutor
    from anlan.tools.policy import TaskCatalog

    e, snapshot, host, budget, log, audit = harness(tmp_path, "disconnect")
    definitions = e.build_dynamic_definitions(snapshot, host, budget).definitions
    catalog = TaskCatalog(snapshot.identity, definitions, snapshot.requests)
    name = definitions[0].name
    value = await ToolExecutor(catalog).execute(name, dict(snapshot.requests)[name])
    assert value["reason"] == "disconnected"
    assert value["evidence_valid"] is False


async def test_timeout_is_distinct_and_failed_wire_is_audited(tmp_path):
    e, snapshot, host, budget, log, audit = harness(tmp_path, "slow")
    definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
    with pytest.raises(TimeoutError):
        await definition.handler(
            snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
        )
    assert budget.wire_calls == 1
    assert audit.records[0]["error_code"] == "timeout"
    assert audit.records[0]["evidence_valid"] is False


async def test_real_http_three_capabilities_and_seventh_call_zero_wire(tmp_path):
    import asyncio
    import socket
    import subprocess
    from dataclasses import replace

    from anlan.tools.dynamic_mcp.runtime import HttpProfile

    e, snapshot, host, budget, log, audit = harness(tmp_path)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    fixture = str(Path("tests/fixtures/dynamic_mcp_equipment_server.py").resolve())
    process = subprocess.Popen(
        [sys.executable, fixture, "http", str(log), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        for _ in range(300):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.025)
        else:
            pytest.fail("synthetic HTTP server not listening")
        host.registry.registration = Registration.model_validate(
            {
                **host.registry.registration.model_dump(mode="json"),
                "connection": dict(transport="streamable_http", target_ref="fixture"),
            }
        )
        host = replace(
            host,
            targets=TrustedTargets(
                "p1",
                (),
                (
                    HttpProfile(
                        "tenant",
                        "fixture",
                        f"http://127.0.0.1:{port}/mcp",
                        synthetic_loopback_http=True,
                    ),
                ),
            ),
        )
        definitions = e.build_dynamic_definitions(snapshot, host, budget).definitions
        for i in range(6):
            definition = definitions[i % 3]
            value = await definition.handler(
                snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
            )
            assert value.evidence.remote.usable
        with pytest.raises(e.RuntimeFailure, match="tool_budget_exhausted"):
            await definitions[0].handler(
                snapshot.identity, json.loads(dict(snapshot.requests)[definitions[0].name])
            )
        wire = [json.loads(line) for line in log.read_text().splitlines()]
        assert sum(item.get("method") == "tools/call" for item in wire) == budget.wire_calls == 6
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.parametrize("action", ["disable", "refresh", "replace"])
def test_real_pg_revocation_during_sdk_call_cancels_actual_wire_and_rejects_publish(
    tmp_path, action
):
    import asyncio

    from test_dynamic_mcp_registry import run, setup

    from anlan.tools.dynamic_mcp.catalog import (
        CatalogScope,
        expected_schemas,
        make_discovery,
        sanitize_tool,
    )

    async def scenario():
        e, snapshot, old_host, budget, log, _ = harness(tmp_path, "slow")
        r, registry, admin, tenant = setup()
        await registry.initialize(admin)
        registration = Registration.model_validate(
            {
                **old_host.registry.registration.model_dump(mode="json"),
                "tenant_id": tenant,
                "state": "registered",
            }
        )
        managed = r.ManagedRegistration(registration, "host", ("reader",))
        await registry.register(admin, managed, "register")
        lease = await registry.reserve_discovery(admin, tenant, "service", 1, "discover")
        discovery = make_discovery(
            discovery_id="synthetic-discovery",
            captured_generation=1,
            protocol_version="2025-11-25",
            server_name="fixture",
            server_version="1",
            discovered_at=datetime.now(timezone.utc),
            tools=tuple(
                sanitize_tool(binding.tool_name, *expected_schemas(binding.capability))
                for binding in registration.bindings
            ),
        )
        await registry.record_discovery(admin, lease, discovery, "discover")
        head = (await registry.get(admin, tenant, "service"))["head"]
        await registry.enable(admin, tenant, "service", 2, head["validation_digest"], "enable")
        snapshot.identity = Identity(tenant_id=tenant, user_id="reader")
        catalog = await registry.load_catalog(
            CatalogScope(
                identity=snapshot.identity,
                capabilities=tuple(b.capability for b in registration.bindings),
                factory_ids=("F001",),
                policy_version="p1",
            )
        )
        snapshot.entries = catalog.entries
        snapshot.requests = tuple(
            (
                entry.alias,
                CapabilityRequest(
                    capability=entry.capability,
                    factory_id="F001",
                    objects=["E001"],
                    queried_at=snapshot.query_at,
                ).model_dump_json(),
            )
            for entry in snapshot.entries
        )
        snapshot.leases = tuple(
            [
                (entry.alias, (await registry.resolve_business(snapshot.identity, entry))[1])
                for entry in snapshot.entries
            ]
        )
        targets = TrustedTargets(
            "p1",
            (
                ExecutableProfile(
                    tenant,
                    "fixture",
                    sys.executable,
                    tuple(registration.connection.argv),
                    str(Path.cwd()),
                ),
            ),
        )
        audit = e.InquiryAuditStore(registry)
        await audit.initialize(admin)
        host = e.ExecutionHost(registry, targets, None, audit, lambda snapshot: True)
        definition = e.build_dynamic_definitions(snapshot, host, budget).definitions[0]
        task = asyncio.create_task(
            definition.handler(
                snapshot.identity, json.loads(dict(snapshot.requests)[definition.name])
            )
        )
        try:
            for _ in range(200):
                if log.exists() and "tools/call" in log.read_text():
                    break
                if task.done():
                    await task
                await asyncio.sleep(0.025)
            else:
                pytest.fail("business wire not observed")
            generation = dict(snapshot.leases)[definition.name].generation
            if action == "replace":
                await registry.replace(admin, tenant, "service", managed, generation, "revoke")
            else:
                await getattr(registry, action)(admin, tenant, "service", generation, "revoke")
            with pytest.raises((r.RegistryError, e.RuntimeFailure), match="stale_generation"):
                await task
            wire = [json.loads(line) for line in log.read_text().splitlines()]
            call_id = next(
                item["request_id"] for item in wire if item.get("method") == "tools/call"
            )
            assert any(item.get("cancelled_id") == call_id for item in wire)
            async with registry._connection() as conn:
                count = await (
                    await conn.execute(
                        "SELECT count(*) AS n FROM anlan_v2.dynamic_mcp_calls WHERE tenant_id=%s",
                        (tenant,),
                    )
                ).fetchone()
            assert count["n"] == 0
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    run(scenario())


def test_pg_failed_receipt_records_only_fixed_error_and_no_evidence():
    from test_dynamic_mcp_registry import discovered, run, setup

    from anlan.tools.dynamic_mcp.catalog import CatalogScope
    from anlan.tools.dynamic_mcp.contracts import HostReceipt

    async def scenario():
        e = api()
        r, registry, admin, tenant = setup()
        await registry.initialize(admin)
        head = await discovered(registry, r, admin, tenant, "service")
        await registry.enable(admin, tenant, "service", 2, head["validation_digest"], "enable")
        identity = Identity(tenant_id=tenant, user_id="reader")
        catalog = await registry.load_catalog(
            CatalogScope(
                identity=identity,
                capabilities=("equipment.asset.query",),
                factory_ids=("F001",),
                policy_version="p1",
            )
        )
        entry = catalog.entries[0]
        _, lease = await registry.resolve_business(identity, entry)
        audit = e.InquiryAuditStore(registry)
        await audit.initialize(admin)
        receipt = HostReceipt(
            service_id="service",
            tool_name=entry.original_name,
            call_id="failed-call",
            received_at=datetime.now(timezone.utc),
            config_version="v1",
            catalog_version=catalog.catalog_id,
            route_version="d1",
            response_sha256="c" * 64,
            selection_reason="single_authorized_source",
        )
        metadata = dict(
            alias=entry.alias,
            capability=entry.capability,
            task_id="task",
            run_id="run",
            correlation_id="corr",
            elapsed_ms=1,
            evidence_valid=False,
            request=CapabilityRequest(
                capability=entry.capability,
                factory_id="F001",
                objects=["E001"],
                queried_at=datetime.now(timezone.utc),
            ),
        )
        with pytest.raises(r.RegistryError, match="invalid_configuration"):
            await audit.publish(identity, lease, receipt, error_code="REMOTE_SECRET", **metadata)
        await audit.publish(identity, lease, receipt, error_code="data_error", **metadata)
        async with registry._connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT receipt_json FROM anlan_v2.dynamic_mcp_calls WHERE tenant_id=%s",
                    (tenant,),
                )
            ).fetchone()
        assert row["receipt_json"]["request"]["objects"] == ["E001"]
        assert row["receipt_json"]["error_code"] == "data_error"
        assert row["receipt_json"]["evidence_valid"] is False
        assert "REMOTE_SECRET" not in json.dumps(row)

    run(scenario())
