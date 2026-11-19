import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anlan.common.models import Identity
from anlan.tools.contracts import FactReferences
from anlan.tools.queries import FactTools

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
ACTOR = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
REFS = FactReferences(worker_id="worker-001", qualification_type="welding", area_id="area-001")


def catalog(handler=None):
    from anlan.tools.builtin import builtin_registry
    from anlan.tools.policy import ToolPolicy

    tools = FactTools(Path("examples/synthetic/facts-v1"), clock=lambda: NOW)
    if handler:
        tools.query_area_status = handler
    return ToolPolicy().snapshot(builtin_registry(tools), ACTOR, REFS)


async def test_executor_boundaries_and_binding():
    from anlan.tools.executor import ToolExecutor

    called = []

    async def handler(actor, params):
        called.append(params)
        return await FactTools(
            Path("examples/synthetic/facts-v1"), clock=lambda: NOW
        ).query_area_status(actor, params)

    executor = ToolExecutor(catalog(handler))
    for name, args, reason in [
        ("approve", "{}", "tool_not_allowed"),
        ("query_area_status", '{"area_id":"other"}', "outside_references"),
        ("query_area_status", '{"area_id":"area-001","tenant_id":"x"}', "invalid_parameters"),
        ("query_area_status", "x" * 4097, "invalid_parameters"),
    ]:
        result = await executor.execute(name, args)
        assert result["reason"] == reason and not result["executed"]
    assert called == []
    result = await executor.execute("query_area_status", '{"area_id":"area-001"}')
    assert result["outcome"] == "ok" and result["evidence_valid"]


@pytest.mark.parametrize("kind", ["type", "tool", "object", "time", "exception", "size"])
async def test_invalid_results_are_not_citable(kind):
    from anlan.tools.executor import ToolExecutor

    async def handler(actor, params):
        value = await FactTools(
            Path("examples/synthetic/facts-v1"), clock=lambda: NOW
        ).query_area_status(actor, params)
        if kind == "exception":
            raise RuntimeError("secret-sentinel")
        return {
            "type": {},
            "tool": value.model_copy(update={"tool": "query_worker_qualification"}),
            "object": value.model_copy(update={"object_id": "other"}),
            "time": value.model_copy(update={"queried_at": NOW - timedelta(days=1)}),
            "size": value.model_copy(update={"message": "x" * 65537}),
        }.get(kind, value)

    result = await ToolExecutor(catalog(handler)).execute(
        "query_area_status", '{"area_id":"area-001"}'
    )
    assert result["reason"] == "data_error" and not result["evidence_valid"]
    assert "secret-sentinel" not in json.dumps(result)


async def test_timeout_and_cancellation():
    from anlan.tools.executor import ToolExecutor

    async def slow(actor, params):
        await asyncio.sleep(10)

    executor = ToolExecutor(catalog(slow), timeout_seconds=0.01)
    result = await executor.execute("query_area_status", '{"area_id":"area-001"}')
    assert result["reason"] == "timeout" and not result["evidence_valid"]
    task = asyncio.create_task(executor.execute("query_area_status", '{"area_id":"area-001"}'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_workflow_rejects_misbound_result_as_final_citation(tmp_path):
    from test_tool_loop import SequenceModel

    from anlan.infrastructure.trace import JsonlTrace
    from anlan.interfaces.cli import DEMO_FIELDS
    from anlan.llm.tool_model import FinalAnswer, ModelTurn, ToolCall
    from anlan.workflows.material_analysis import OfflineAnalyzer
    from anlan.workflows.service import WorkflowService
    from anlan.workflows.tool_loop import check_facts_agent

    tools = FactTools(Path("examples/synthetic/facts-v1"), clock=lambda: NOW)
    original = tools.query_area_status

    async def wrong(actor, parameters):
        return (await original(actor, parameters)).model_copy(update={"object_id": "other"})

    tools.query_area_status = wrong
    model = SequenceModel(
        [
            ModelTurn(
                calls=[
                    ToolCall(
                        id="area", name="query_area_status", arguments='{"area_id":"area-001"}'
                    ),
                    ToolCall(
                        id="worker",
                        name="query_worker_qualification",
                        arguments=json.dumps(
                            {"worker_id": "worker-001", "qualification_type": "welding"}
                        ),
                    ),
                ]
            ),
            ModelTurn(final=FinalAnswer(summary="候选", evidence_call_ids=["area", "worker"])),
        ]
    )
    service = WorkflowService(OfflineAnalyzer())
    task = await service.start(ACTOR, DEMO_FIELDS)
    report = await check_facts_agent(
        service,
        ACTOR,
        task["task_id"],
        REFS.model_dump(),
        tools,
        model,
        JsonlTrace(tmp_path / "trace.jsonl"),
    )
    assert report["stop_reason"] == "missing_evidence"
    assert report["summary"] is None
    assert report["results"][0]["reason"] == "data_error"
