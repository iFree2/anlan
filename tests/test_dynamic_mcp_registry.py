import asyncio
import hashlib
import importlib.util
import os
import selectors
import uuid

import pytest


def run(coro):
    return asyncio.run(
        coro, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    )


def api():
    assert importlib.util.find_spec("anlan.tools.dynamic_mcp.registry"), (
        "registry implementation missing"
    )
    from anlan.tools.dynamic_mcp import registry

    return registry


def test_admin_policy_is_independent_and_rejects_normal_bearer():
    r = api()
    token = "mcpadm_" + "ab" * 32
    policy = r.AdminPolicy(
        subject="host",
        tenant_ids=frozenset({"synthetic"}),
        actions=r.ADMIN_ACTIONS,
        policy_version="p1",
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
    )
    admin = policy.authenticate(token)
    policy.authorize(admin, "synthetic", "register")
    for identity in ["Bearer normal-token", object(), None]:
        with pytest.raises(r.RegistryError, match="access_denied"):
            policy.authorize(identity, "synthetic", "register")
    with pytest.raises(r.RegistryError, match="access_denied"):
        policy.authenticate("ordinary-business-token")
    with pytest.raises(r.RegistryError, match="access_denied"):
        policy.authorize(admin, "other", "register")


def managed(r, tenant, service):
    from anlan.tools.dynamic_mcp.contracts import Registration

    reg = Registration.model_validate(
        dict(
            schema_version="dynamic-registration-v1",
            data_origin="SYNTHETIC",
            tenant_id=tenant,
            service_id=service,
            config_version="v1",
            state="registered",
            connection=dict(transport="stdio", executable_ref="fixture", argv=[]),
            factories=[dict(factory_id="F001", aliases=["synthetic"])],
            bindings=[
                dict(
                    capability="equipment.asset.query",
                    contract_version="1",
                    tool_name="assets",
                    factory_ids=["F001"],
                )
            ],
        )
    )
    return r.ManagedRegistration(reg, "host", ("reader",))


def setup():
    r = api()
    dsn = os.environ.get("ANLAN_MCP_TEST_DATABASE_URL") or os.environ["ANLAN_TEST_DATABASE_URL"]
    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost"}
    tenant = "synthetic-" + uuid.uuid4().hex[:12]
    policy = r.AdminPolicy(
        "host",
        frozenset({tenant}),
        r.ADMIN_ACTIONS,
        "p1",
        hashlib.sha256(("mcpadm_" + "ab" * 32).encode()).hexdigest(),
    )
    admin = policy.authenticate("mcpadm_" + "ab" * 32)

    async def synthetic_target_validator(principal, registration, generation):
        policy.authorize(principal, registration.tenant_id, "enable")
        assert registration.data_origin == "SYNTHETIC"
        assert registration.connection.executable_ref == "fixture"

    return (
        r,
        r.DynamicMcpRegistry(dsn, policy, enable_validator=synthetic_target_validator),
        admin,
        tenant,
    )


def test_pg_cas_idempotence_immutable_history_and_revocation():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        await store.initialize(admin)
        m = managed(r, tenant, "service")
        receipt = await store.register(admin, m, "register")
        assert receipt.generation == 1
        assert await store.register(admin, m, "register") == receipt
        with pytest.raises(r.RegistryError, match="idempotency_conflict"):
            await store.disable(admin, tenant, "service", 1, "register")
        results = await asyncio.gather(
            *(store.disable(admin, tenant, "service", 1, "disable-" + str(i)) for i in range(2)),
            return_exceptions=True,
        )
        assert sum(isinstance(x, r.CommandReceipt) for x in results) == 1
        assert (
            sum(isinstance(x, r.RegistryError) and x.code == "version_conflict" for x in results)
            == 1
        )
        from psycopg import AsyncConnection

        from anlan.infrastructure.db import conninfo

        async with await AsyncConnection.connect(conninfo(store.dsn)) as conn:
            for table in ["dynamic_mcp_revisions", "dynamic_mcp_commands"]:
                with pytest.raises(Exception):
                    async with conn.transaction():
                        await conn.execute(
                            f"UPDATE anlan_v2.{table} SET tenant_id=tenant_id WHERE tenant_id=%s",
                            (tenant,),
                        )
        assert (await store.get(admin, tenant, "service"))["head"]["state"] == "disabled"

    run(scenario())


def test_pg_network_reservation_is_single_use_and_unknown_is_terminal():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        await store.register(admin, managed(r, tenant, "service"), "register")
        lease = await store.reserve_discovery(
            admin, tenant, "service", 1, "discover", deadline_seconds=-1
        )
        assert lease.generation == 1
        with pytest.raises(r.RegistryError, match="in_progress"):
            await store.reserve_discovery(admin, tenant, "service", 1, "discover")
        result = await store.reconcile(admin, tenant, "discover")
        assert result.status == "outcome_unknown"
        with pytest.raises(r.RegistryError, match="outcome_unknown"):
            await store.reserve_discovery(admin, tenant, "service", 1, "discover")
        assert (await store.get(admin, tenant, "service"))["head"]["generation"] == 1

    run(scenario())


async def discovered(store, r, admin, tenant, service):
    from datetime import datetime, timezone

    from anlan.tools.dynamic_mcp.catalog import expected_schemas, make_discovery, sanitize_tool

    await store.register(admin, managed(r, tenant, service), "reg-" + service)
    lease = await store.reserve_discovery(admin, tenant, service, 1, "discover-" + service)
    inp, out = expected_schemas("equipment.asset.query")
    inp["description"] = "SECRET_REMOTE_DESCRIPTION"
    snapshot = make_discovery(
        discovery_id=uuid.uuid4().hex,
        captured_generation=1,
        protocol_version="2025-11-25",
        server_name="synthetic",
        server_version="1",
        discovered_at=datetime.now(timezone.utc),
        tools=(sanitize_tool("assets", inp, out),),
    )
    receipt = await store.record_discovery(admin, lease, snapshot, "discover-" + service)
    assert receipt.generation == 2
    head = (await store.get(admin, tenant, service))["head"]
    return head


def test_two_distinct_services_competing_enable_only_one_succeeds():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        heads = [await discovered(store, r, admin, tenant, s) for s in ["a", "b"]]
        results = await asyncio.gather(
            *(
                store.enable(admin, tenant, s, 2, h["validation_digest"], "enable-" + s)
                for s, h in zip(["a", "b"], heads)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(x, r.CommandReceipt) for x in results) == 1
        assert (
            sum(isinstance(x, r.RegistryError) and x.code == "source_conflict" for x in results)
            == 1
        )
        states = [(await store.get(admin, tenant, s))["head"]["state"] for s in ["a", "b"]]
        assert sorted(states) == ["enabled", "validated"]
        from psycopg import AsyncConnection

        from anlan.infrastructure.db import conninfo

        async with await AsyncConnection.connect(conninfo(store.dsn)) as conn:
            rows = await (
                await conn.execute(
                    "SELECT tools_json::text FROM anlan_v2.dynamic_mcp_discoveries "
                    "WHERE tenant_id=%s",
                    (tenant,),
                )
            ).fetchall()
            assert "SECRET_REMOTE_DESCRIPTION" not in str(rows)
            with pytest.raises(Exception):
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM anlan_v2.dynamic_mcp_discoveries WHERE tenant_id=%s", (tenant,)
                    )

    run(scenario())


def test_disable_rejects_late_discovery_and_refresh_revokes_lease():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        await discovered(store, r, admin, tenant, "service")
        from anlan.tools.dynamic_mcp.catalog import CatalogLease

        lease = CatalogLease(
            tenant_id=tenant,
            service_id="service",
            generation=2,
            config_revision=1,
            discovery_id=(await store.get(admin, tenant, "service"))["head"]["discovery_id"],
            target_policy_version="p1",
            credential_generation="",
        )
        await store.assert_current(lease)
        await store.refresh(admin, tenant, "service", 2, "refresh")
        with pytest.raises(r.RegistryError, match="stale_generation"):
            await store.assert_current(lease)
        reserved = await store.reserve_discovery(admin, tenant, "service", 3, "late")
        await store.disable(admin, tenant, "service", 3, "disable")
        from datetime import datetime, timezone

        from anlan.tools.dynamic_mcp.catalog import expected_schemas, make_discovery, sanitize_tool

        inp, out = expected_schemas("equipment.asset.query")
        snapshot = make_discovery(
            discovery_id=uuid.uuid4().hex,
            captured_generation=3,
            protocol_version="2025-11-25",
            server_name="synthetic",
            server_version="1",
            discovered_at=datetime.now(timezone.utc),
            tools=(sanitize_tool("assets", inp, out),),
        )
        result = await store.record_discovery(admin, reserved, snapshot, "late")
        assert result.error_code == "stale_generation"
        assert (await store.get(admin, tenant, "service"))["head"]["state"] == "disabled"

    run(scenario())


def test_mutation_during_await_does_not_change_registered_revision():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        m = managed(r, tenant, "safe")
        original = store._lock

        async def mutate(conn, key):
            m.registration.config_version = "mutated"
            await original(conn, key)

        store._lock = mutate
        await store.register(admin, m, "register")
        stored = await store.get(admin, tenant, "safe")
        assert stored["revision"]["registration_json"]["config_version"] == "v1"

    run(scenario())


def test_ordinary_identity_and_wrong_tenant_never_open_database():
    async def scenario():
        r = api()
        policy = r.AdminPolicy("host", frozenset({"synthetic"}), r.ADMIN_ACTIONS, "p1", "0" * 64)
        store = r.DynamicMcpRegistry("invalid-dsn-must-not-be-opened", policy)
        for principal in [object(), "Bearer abc", None]:
            with pytest.raises(r.RegistryError, match="access_denied"):
                await store.get(principal, "synthetic", "hidden")

    run(scenario())


def test_enable_fails_closed_without_host_target_verifier():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        head = await discovered(store, r, admin, tenant, "service")
        store.enable_validator = None
        with pytest.raises(r.RegistryError, match="target_not_allowed"):
            await store.enable(admin, tenant, "service", 2, head["validation_digest"], "enable")

    run(scenario())


def test_failed_network_operation_has_terminal_safe_receipt():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        await store.register(admin, managed(r, tenant, "service"), "register")
        lease = await store.reserve_discovery(admin, tenant, "service", 1, "failed-discover")
        receipt = await store.fail_discovery(admin, lease, "failed-discover", "disconnected")
        assert receipt.status == "failed"
        assert receipt.error_code == "disconnected"
        assert (
            await store.reserve_discovery(admin, tenant, "service", 1, "failed-discover") == receipt
        )

    run(scenario())


def test_inspect_includes_only_safe_discovery_summary():
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        await discovered(store, r, admin, tenant, "service")
        result = await store.get(admin, tenant, "service")
        assert result["diagnostic"]["tool_count"] == 1
        assert result["diagnostic"]["validation_status"] == "validated"
        assert result["diagnostic"]["error_codes"] == []
        rows = await store.list(admin, tenant)
        assert rows[0]["diagnostic"] == result["diagnostic"]

    run(scenario())


def test_enable_rejects_registration_replaced_between_scope_read_and_head_lock():
    from dataclasses import replace
    from datetime import UTC, datetime

    from anlan.tools.dynamic_mcp.catalog import (
        expected_schemas,
        make_discovery,
        sanitize_tool,
        validate_discovery,
    )

    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        await discovered(store, r, admin, tenant, "service")
        second = r.DynamicMcpRegistry(
            store.dsn, store.admin_authorizer, enable_validator=store.enable_validator
        )
        replacement = managed(r, tenant, "service")
        data = replacement.registration.model_dump(mode="json")
        data["factories"][0]["factory_id"] = "F002"
        data["bindings"][0]["factory_ids"] = ["F002"]
        registration = replacement.registration.model_validate(data)
        replacement = replace(replacement, registration=registration)
        snapshot = make_discovery(
            discovery_id=uuid.uuid4().hex,
            captured_generation=3,
            protocol_version="v1",
            server_name="synthetic",
            server_version="1",
            discovered_at=datetime.now(UTC),
            tools=(sanitize_tool("assets", *expected_schemas("equipment.asset.query")),),
        )
        report = validate_discovery(registration, snapshot)
        original_lock = store._lock
        changed = False

        async def interleave(conn, key):
            nonlocal changed
            if '"source"' in key and not changed:
                changed = True
                await second.replace(admin, tenant, "service", replacement, 2, "replace")
                lease = await second.reserve_discovery(admin, tenant, "service", 3, "new-discovery")
                await second.record_discovery(admin, lease, snapshot, "new-discovery")
            await original_lock(conn, key)

        store._lock = interleave
        with pytest.raises(r.RegistryError, match="version_conflict"):
            await store.enable(admin, tenant, "service", 4, report.digest, "racing-enable")
        head = (await second.get(admin, tenant, "service"))["head"]
        assert changed and head["generation"] == 4 and head["state"] == "validated"

    run(scenario())
