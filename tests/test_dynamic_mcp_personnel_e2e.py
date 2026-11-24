"""Three real personnel capabilities through scripted model, Policy and Executor."""

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_dynamic_mcp_registry import managed, run, setup

from anlan.common.models import Identity
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.tools.dynamic_mcp.catalog import CatalogScope
from anlan.tools.dynamic_mcp.personnel import (
    PERSONNEL_CAPABILITIES,
    Contractor,
    Person,
    PersonnelGrant,
    PersonnelPolicy,
    PersonnelRequest,
)
from anlan.tools.dynamic_mcp.runtime import (
    EnvironmentCredentials,
    ExecutableProfile,
    RuntimeManager,
    TrustedTargets,
)
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService


@pytest.mark.parametrize(
    "mode", ["normal", "partial_empty", "unknown", "wrong_category", "wrong_object"]
)
def test_real_personnel_sdk_pg_scripted_chain(tmp_path, mode):
    async def scenario():
        from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel
        from anlan.tools.dynamic_mcp.execution import ExecutionHost, InquiryAuditStore
        from anlan.workflows.external_inquiry_personnel import check_external_personnel

        r, registry, admin, tenant = setup()
        await registry.initialize(admin)
        fixture = str(Path("tests/fixtures/dynamic_mcp_personnel_server.py").resolve())
        assert Path(fixture).exists(), "personnel SDK fixture missing"
        events = tmp_path / "wire.jsonl"
        argv = (fixture, mode, str(events))
        original = managed(r, tenant, "personnel")
        data = original.registration.model_dump(mode="json")
        data["connection"]["argv"] = list(argv)
        data["bindings"] = [
            dict(capability=cap, contract_version="1", tool_name=cap, factory_ids=["F001"])
            for cap in PERSONNEL_CAPABILITIES
        ]
        registration = original.registration.model_validate(data)
        await registry.register(admin, replace(original, registration=registration), "register")
        targets = TrustedTargets(
            "p1", (ExecutableProfile(tenant, "fixture", sys.executable, argv, str(Path.cwd())),), ()
        )
        credentials = EnvironmentCredentials({})
        manager = RuntimeManager(targets, credentials, registry)
        lease = await registry.reserve_discovery(admin, tenant, "personnel", 1, "discover")
        discovery = await manager.discover(admin, registration, lease)
        recorded = await registry.record_discovery(admin, lease, discovery, "discover")
        state = await registry.get(admin, tenant, "personnel")
        await registry.enable(
            admin,
            tenant,
            "personnel",
            recorded.generation,
            state["head"]["validation_digest"],
            "enable",
        )
        actor = Identity(tenant_id=tenant, user_id="reader")
        service = WorkflowService(OfflineAnalyzer())
        before = await service.start(actor, DEMO_FIELDS)
        policy = PersonnelPolicy(
            policy_version="p1",
            tenant_id=tenant,
            directory_version="directory-v1",
            factories={"F001": ("一厂", "1工厂")},
            contractors={"contractor-1": Contractor(name="合成承包商", factory_ids=("F001",))},
            persons={
                "person-1": Person(name="张三", contractor_id="contractor-1", factory_ids=("F001",))
            },
            users={
                "reader": PersonnelGrant(
                    factory_ids=("F001",),
                    contractor_ids=("contractor-1",),
                    person_ids=("person-1",),
                    qualification_categories=("hot-work",),
                    training_categories=("safety",),
                    capabilities=PERSONNEL_CAPABILITIES,
                )
            },
        )
        request = PersonnelRequest(
            task_id=before["task_id"],
            factory_alias="1工厂",
            contractor_id="contractor-1",
            person_id="person-1",
            qualification_category="hot-work",
            training_category="safety",
            question="承包商资质、人员培训与准入分别如何？",
        )
        audit = InquiryAuditStore(registry)
        await audit.initialize(admin)
        host = ExecutionHost(registry, targets, credentials, audit, lambda snapshot: True)
        query_at = datetime(2026, 1, 1, tzinfo=UTC)
        report = await check_external_personnel(
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
        assert report["stop_reason"] == (
            "missing_evidence" if mode in {"wrong_category", "wrong_object"} else "completed"
        ), report
        assert report["summary_status"] == "unverified_candidate"
        if mode in {"partial_empty", "unknown"}:
            assert report["unknown_capabilities"] == list(PERSONNEL_CAPABILITIES)
            assert all(not result["usable"] for result in report["results"])
        if mode == "partial_empty":
            assert report["partial_capabilities"] == list(PERSONNEL_CAPABILITIES)
        if mode == "wrong_object":
            assert report["missing_capabilities"] == list(PERSONNEL_CAPABILITIES)
        if mode == "wrong_category":
            assert report["missing_capabilities"] == list(PERSONNEL_CAPABILITIES[:2])
        invalid_caps = (
            set(PERSONNEL_CAPABILITIES)
            if mode == "wrong_object"
            else set(PERSONNEL_CAPABILITIES[:2])
            if mode == "wrong_category"
            else set()
        )
        for result in report["results"]:
            if result["required_capability"] in invalid_caps:
                assert result["reason"] == "data_error"
                assert result["evidence_valid"] is False
            else:
                assert result["evidence_valid"] is True
        if mode == "normal":
            assert not report["unknown_capabilities"]
            records = [r["evidence"]["remote"]["data"][0] for r in report["results"]]
            assert [r["object_id"] for r in records] == ["contractor-1", "person-1", "person-1"]
            assert [r["status"] for r in records] == ["active", "completed", "denied"]
            assert "denied" in report["summary"]["summary"]

        assert report["attempts"] == report["wire_calls"] == 3
        assert all(result["evidence_valid"] for result in report["results"]) == (
            mode not in {"wrong_category", "wrong_object"}
        )
        assert await service.get(actor, before["task_id"]) == before
        async with registry._connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT call_id,receipt_json FROM anlan_v2.dynamic_mcp_calls "
                    "WHERE tenant_id=%s AND run_id=%s",
                    (tenant, report["run_id"]),
                )
            ).fetchall()
        assert {row["call_id"] for row in rows if row["receipt_json"]["evidence_valid"]} == {
            item["receipt_call_id"] for item in report["results"] if item["evidence_valid"]
        }
        for row in rows:
            receipt = row["receipt_json"]
            params = receipt["request"]
            invalid = params["capability"] in invalid_caps
            assert receipt["evidence_valid"] is (not invalid)
            assert receipt["error_code"] == ("data_error" if invalid else None)
            assert params["objects"] == (
                ["contractor-1"]
                if params["capability"] == PERSONNEL_CAPABILITIES[0]
                else ["person-1"]
            )

        assert len(rows) == 3

        wire = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        assert sum(event.get("method") == "tools/call" for event in wire) == 3
        assert (
            len(
                (
                    await registry.load_catalog(
                        CatalogScope(
                            identity=actor,
                            capabilities=PERSONNEL_CAPABILITIES,
                            factory_ids=("F001",),
                            policy_version="p1",
                        )
                    )
                ).entries
            )
            == 3
        )
        for result in report["results"]:
            if not result["evidence_valid"]:
                continue
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
