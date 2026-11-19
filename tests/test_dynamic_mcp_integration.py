"""Real SDK discovery to isolated PG publication; business calls remain absent."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_dynamic_mcp_registry import managed, run, setup

from anlan.common.models import Identity
from anlan.tools.dynamic_mcp.catalog import CatalogScope
from anlan.tools.dynamic_mcp.runtime import (
    EnvironmentCredentials,
    ExecutableProfile,
    RuntimeManager,
    TrustedTargets,
)


def test_real_sdk_discovery_registry_publication_and_revocation(tmp_path):
    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        event_file = tmp_path / "business.jsonl"
        fixture = str(Path("tests/fixtures/dynamic_mcp_server.py").resolve())
        argv = (fixture, "business", str(event_file))
        value = managed(r, tenant, "service")
        registration = value.registration.model_copy(deep=True)
        registration.connection.argv = list(argv)
        value = replace(value, registration=registration)
        await store.register(admin, value, "register")
        lease = await store.reserve_discovery(admin, tenant, "service", 1, "discover")
        targets = TrustedTargets(
            "p1", (ExecutableProfile(tenant, "fixture", sys.executable, argv, str(Path.cwd())),), ()
        )
        manager = RuntimeManager(targets, EnvironmentCredentials({}), store)
        snapshot = await manager.discover(admin, registration, lease)
        assert "REMOTE_SECRET" not in snapshot.model_dump_json()
        receipt = await store.record_discovery(admin, lease, snapshot, "discover")
        assert receipt.status == "completed"
        state = await store.get(admin, tenant, "service")
        assert state["head"]["state"] == "validated"
        enabled = await store.enable(
            admin,
            tenant,
            "service",
            receipt.generation,
            state["head"]["validation_digest"],
            "enable",
        )
        scope = CatalogScope(
            identity=Identity(tenant_id=tenant, user_id="reader"),
            capabilities=("equipment.asset.query",),
            factory_ids=("F001",),
            policy_version="p1",
        )
        catalog = await store.load_catalog(scope)
        assert len(catalog.entries) == 1
        assert not (
            await store.load_catalog(scope.model_copy(update={"policy_version": "retired"}))
        ).entries
        assert not (
            await store.load_catalog(scope.model_copy(update={"policy_version": ""}))
        ).entries
        assert catalog.entries[0].generation == enabled.generation
        disabled = await store.disable(admin, tenant, "service", enabled.generation, "disable")
        assert disabled.generation > enabled.generation
        assert not (await store.load_catalog(scope)).entries
        with pytest.raises(r.RegistryError, match="stale_generation"):
            await store.assert_current(lease)
        assert (await manager.close()).status == "closed"
        events = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        assert any(e.get("method") == "tools/list" for e in events)
        assert not any(e.get("method") == "tools/call" for e in events)

    run(scenario())


def test_cli_true_discovery_enable_gate_and_no_business_call(tmp_path):
    import hashlib
    import os
    import subprocess

    r, _, _, tenant = setup()
    fixture = str(Path("tests/fixtures/dynamic_mcp_server.py").resolve())
    event_file = tmp_path / "cli-events.jsonl"
    argv = [fixture, "business", str(event_file)]
    registration = managed(r, tenant, "cli-service").registration.model_dump(mode="json")
    registration["connection"].update(argv=argv, credential_ref="credential-1")
    managed_path = tmp_path / "managed.json"
    managed_path.write_text(
        json.dumps(
            {"registration": registration, "owner_subject": "host", "reader_user_ids": ["reader"]}
        ),
        encoding="utf-8",
    )
    token = "mcpadm_" + "ab" * 32
    config = {
        "purpose": "dynamic_mcp_admin",
        "subject": "host",
        "tenant_ids": [tenant],
        "actions": sorted(r.ADMIN_ACTIONS),
        "policy_version": "p1",
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "trusted_targets": {
            "executable_profiles": [
                {
                    "tenant_id": tenant,
                    "executable_ref": "fixture",
                    "executable": sys.executable,
                    "argv": argv,
                    "cwd": str(Path.cwd()),
                    "credential_env": "MCP_FIXTURE_SECRET",
                }
            ]
        },
        "credentials": {
            tenant: {
                "credential-1": {"environment_variable": "MCP_SYNTHETIC_SECRET", "generation": "g1"}
            }
        },
    }
    config_path = tmp_path / "admin.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    environment = {
        **os.environ,
        "ANLAN_MCP_ADMIN_POLICY": str(config_path),
        "ANLAN_MCP_ADMIN_TOKEN": token,
        "MCP_SYNTHETIC_SECRET": "CREDENTIAL_SENTINEL",
        "ANLAN_DATABASE_URL": os.environ.get(
            "ANLAN_MCP_TEST_DATABASE_URL", os.environ["ANLAN_TEST_DATABASE_URL"]
        ),
    }

    def command(*args, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "anlan.interfaces.mcp_registry_cli", *args],
            env=environment,
            capture_output=True,
            text=True,
            timeout=35,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        assert token not in result.stdout + result.stderr
        assert "CREDENTIAL_SENTINEL" not in result.stdout + result.stderr
        return json.loads(result.stdout)

    command("initialize")
    command("register", "--file", str(managed_path), "--command-id", "register")
    common = ("--tenant", tenant, "--service", "cli-service")
    receipt = command("discover", *common, "--expected-generation", "1", "--command-id", "discover")
    state = command("inspect", *common)["services"][0]
    assert state["state"] == "validated"
    generation = str(receipt["generation"])
    del environment["MCP_SYNTHETIC_SECRET"]
    rejected = command(
        "enable",
        *common,
        "--expected-generation",
        generation,
        "--validation-digest",
        state["validation_digest"],
        "--command-id",
        "denied-enable",
        expected=5,
    )
    assert rejected["error_code"] == "credential_unavailable"
    environment["MCP_SYNTHETIC_SECRET"] = "CREDENTIAL_SENTINEL"
    enabled = command(
        "enable",
        *common,
        "--expected-generation",
        generation,
        "--validation-digest",
        state["validation_digest"],
        "--command-id",
        "enable",
    )
    command(
        "disable",
        *common,
        "--expected-generation",
        str(enabled["generation"]),
        "--command-id",
        "disable",
    )
    assert command("inspect", *common)["services"][0]["state"] == "disabled"
    events = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
    assert not any(event.get("method") == "tools/call" for event in events)


def test_real_pg_disable_cancels_inflight_sdk_discovery(tmp_path):
    import asyncio

    from anlan.tools.dynamic_mcp.runtime import RuntimeFailure

    async def scenario():
        r, store, admin, tenant = setup()
        await store.initialize(admin)
        fixture = str(Path("tests/fixtures/dynamic_mcp_server.py").resolve())
        event_file = tmp_path / "revoked.jsonl"
        argv = (fixture, "slow", str(event_file))
        value = managed(r, tenant, "service")
        registration = value.registration.model_copy(deep=True)
        registration.connection.argv = list(argv)
        await store.register(admin, replace(value, registration=registration), "register")
        lease = await store.reserve_discovery(admin, tenant, "service", 1, "discover")
        manager = RuntimeManager(
            TrustedTargets(
                "p1",
                (ExecutableProfile(tenant, "fixture", sys.executable, argv, str(Path.cwd())),),
                (),
            ),
            EnvironmentCredentials({}),
            store,
        )
        task = asyncio.create_task(manager.discover(admin, registration, lease))
        for _ in range(300):
            if event_file.exists() and '"tools/list"' in event_file.read_text(encoding="utf-8"):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("synthetic SDK discovery did not start")
        await store.disable(admin, tenant, "service", 1, "disable")
        with pytest.raises(RuntimeFailure, match="stale_generation"):
            await asyncio.wait_for(task, 10)
        assert (await store.get(admin, tenant, "service"))["head"]["state"] == "disabled"
        events = [json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()]
        request_id = next(e["request_id"] for e in events if e.get("method") == "tools/list")
        assert any(e.get("cancelled_id") == request_id for e in events)
        assert (await manager.close()).status == "closed"

    run(scenario())
