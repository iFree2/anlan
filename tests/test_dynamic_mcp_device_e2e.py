"""Three real device capabilities through scripted model, Policy and Executor."""

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from test_dynamic_mcp_registry import managed, run, setup

from anlan.common.models import Identity
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.tools.dynamic_mcp.catalog import CatalogScope
from anlan.tools.dynamic_mcp.routing import (
    EQUIPMENT_CAPABILITIES,
    InquiryPolicyConfig,
    InquiryRequest,
    InquiryUserGrant,
)
from anlan.tools.dynamic_mcp.runtime import (
    EnvironmentCredentials,
    ExecutableProfile,
    RuntimeManager,
    TrustedTargets,
)
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService


def test_real_three_capability_scripted_device_chain_preserves_query_time_and_audit(tmp_path):
    async def scenario():
        from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel
        from anlan.tools.dynamic_mcp.execution import ExecutionHost, InquiryAuditStore
        from anlan.workflows.external_inquiry import check_external_inquiry

        r, registry, admin, tenant = setup()
        await registry.initialize(admin)
        fixture = str(Path("tests/fixtures/dynamic_mcp_equipment_server.py").resolve())
        events = tmp_path / "wire.jsonl"
        argv = (fixture, "normal", str(events))
        original = managed(r, tenant, "equipment")
        data = original.registration.model_dump(mode="json")
        data["connection"]["argv"] = list(argv)
        data["bindings"] = [
            dict(capability=cap, contract_version="1", tool_name=cap, factory_ids=["F001"])
            for cap in EQUIPMENT_CAPABILITIES
        ]
        registration = original.registration.model_validate(data)
        await registry.register(admin, replace(original, registration=registration), "register")
        targets = TrustedTargets(
            "p1", (ExecutableProfile(tenant, "fixture", sys.executable, argv, str(Path.cwd())),), ()
        )
        credentials = EnvironmentCredentials({})
        manager = RuntimeManager(targets, credentials, registry)
        lease = await registry.reserve_discovery(admin, tenant, "equipment", 1, "discover")
        discovery = await manager.discover(admin, registration, lease)
        recorded = await registry.record_discovery(admin, lease, discovery, "discover")
        state = await registry.get(admin, tenant, "equipment")
        await registry.enable(
            admin,
            tenant,
            "equipment",
            recorded.generation,
            state["head"]["validation_digest"],
            "enable",
        )
        actor = Identity(tenant_id=tenant, user_id="reader")
        service = WorkflowService(OfflineAnalyzer())
        before = await service.start(actor, DEMO_FIELDS)
        policy = InquiryPolicyConfig(
            "p1",
            tenant,
            "directory-v1",
            {"F001": ("一厂", "1工厂")},
            {
                "reader": InquiryUserGrant(
                    factory_ids=("F001",),
                    equipment_ids=("crane-1",),
                    capabilities=EQUIPMENT_CAPABILITIES,
                )
            },
        )
        request = InquiryRequest(
            task_id=before["task_id"],
            factory_alias="1工厂",
            equipment_id="crane-1",
            question="检验及未关闭故障情况",
        )
        audit = InquiryAuditStore(registry)
        await audit.initialize(admin)
        host = ExecutionHost(registry, targets, credentials, audit, lambda snapshot: True)
        query_at = datetime(2026, 1, 1, tzinfo=UTC)
        report = await check_external_inquiry(
            service,
            actor,
            request,
            policy,
            registry,
            host,
            ScriptedDynamicToolModel(),
            JsonlTrace(tmp_path / "trace.jsonl"),
            query_at=query_at,
        )
        assert report["stop_reason"] == "completed", report["evidence_warnings"]
        assert report["attempts"] == report["wire_calls"] == 3
        assert all(result["evidence_valid"] for result in report["results"])
        assert await service.get(actor, before["task_id"]) == before
        async with registry._connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT call_id,receipt_json FROM anlan_v2.dynamic_mcp_calls "
                    "WHERE tenant_id=%s AND run_id=%s",
                    (tenant, report["run_id"]),
                )
            ).fetchall()
        assert {row["call_id"] for row in rows} == {
            item["receipt_call_id"] for item in report["results"]
        }
        assert len(rows) == 3

        wire = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        assert sum(event.get("method") == "tools/call" for event in wire) == 3
        assert (
            len(
                (
                    await registry.load_catalog(
                        CatalogScope(
                            identity=actor,
                            capabilities=EQUIPMENT_CAPABILITIES,
                            factory_ids=("F001",),
                            policy_version="p1",
                        )
                    )
                ).entries
            )
            == 3
        )
        for result in report["results"]:
            evidence = result["evidence"]
            queried = datetime.fromisoformat(
                evidence["remote"]["queried_at"].replace("Z", "+00:00")
            )
            received = datetime.fromisoformat(
                evidence["host"]["received_at"].replace("Z", "+00:00")
            )
            assert queried == query_at and received > query_at
        assert (await manager.close()).status == "closed"

    run(scenario())
