import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.tool_model import FinalAnswer, ModelTurn, ScriptedToolModel, ToolCall
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService

OWNER = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
REFS = {"worker_id": "worker-001", "qualification_type": "welding", "area_id": "area-001"}


def tools():
    return FactTools(Path("examples/synthetic/facts-v1"),
                     clock=lambda: datetime.fromisoformat("2026-09-20T12:00:00+00:00"))


async def scenario(model, tmp_path, **kwargs):
    from anlan.workflows.tool_loop import check_facts_agent
    service = WorkflowService(OfflineAnalyzer())
    before = await service.start(OWNER, DEMO_FIELDS)
    report = await check_facts_agent(service, OWNER, before["task_id"], REFS, tools(), model,
                                     JsonlTrace(tmp_path / "trace.jsonl"), **kwargs)
    assert await service.get(OWNER, before["task_id"]) == before
    assert len(await service.history(OWNER, before["task_id"])) == 1
    return report


async def test_scripted_loop_observes_tools_and_stops_without_mutating_material(tmp_path):
    report = await scenario(ScriptedToolModel(), tmp_path)
    assert report["stop_reason"] == "completed"
    assert report["mode"] == "scripted_double"
    assert report["model_steps"] == 2 and report["tool_calls"] == 2
    assert report["summary_status"] == "unverified_candidate"
    assert [r["outcome"] for r in report["results"]] == ["ok", "ok"]
    assert report["requests_this_run"] == 0


class SequenceModel:
    mode = "scripted_double"

    def __init__(self, turns):
        self.turns = iter(turns)
        self.messages = []

    async def next(self, messages, run_id):
        self.messages.append(json.loads(json.dumps(messages)))
        value = next(self.turns)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.parametrize("name,args,reason", [
    ("approve_work", {}, "tool_not_allowed"),
    ("query_area_status", {"area_id": "area-expired"}, "outside_references"),
    ("query_area_status", {"area_id": "area-001", "tenant_id": "other"}, "invalid_parameters"),
    ("query_area_status", "not json", "invalid_parameters"),
])
async def test_illegal_actions_become_observations_without_execution(tmp_path, name, args, reason):
    model = SequenceModel([
        ModelTurn(calls=[ToolCall(id="bad-1", name=name,
                                 arguments=args if isinstance(args, str) else json.dumps(args))]),
        ModelTurn(final=FinalAnswer(summary="候选", evidence_call_ids=["bad-1"])),
    ])
    report = await scenario(model, tmp_path)
    assert report["results"][0]["reason"] == reason
    assert report["results"][0]["executed"] is False
    assert report["stop_reason"] == "missing_evidence"
    assert model.messages[1][-1]["role"] == "tool"
    assert model.messages[1][-1]["tool_call_id"] == "bad-1"


async def test_repeated_call_id_is_rejected_before_second_execution(tmp_path):
    turn = ModelTurn(calls=[ToolCall(id="same", name="query_area_status",
                                    arguments=json.dumps({"area_id": "area-001"}))])
    report = await scenario(SequenceModel([turn, turn]), tmp_path)
    assert report["stop_reason"] == "duplicate_call_id"
    assert report["tool_calls"] == 1


async def test_step_budget_stops_repeated_actions(tmp_path):
    turns = [ModelTurn(calls=[ToolCall(id=f"area-{i}", name="query_area_status",
                                      arguments=json.dumps({"area_id": "area-001"}))])
             for i in range(3)]
    report = await scenario(SequenceModel(turns), tmp_path)
    assert report["stop_reason"] == "step_budget_exceeded"
    assert report["model_steps"] == 3


async def test_tool_budget_is_checked_before_execution(tmp_path):
    from anlan.workflows.tool_loop import LoopLimits
    report = await scenario(ScriptedToolModel(), tmp_path, limits=LoopLimits(max_tool_calls=1))
    assert report["stop_reason"] == "tool_budget_exceeded"
    assert report["tool_calls"] == 1 and len(report["results"]) == 1


async def test_model_failure_preserves_previous_tool_result(tmp_path):
    model = SequenceModel([
        ModelTurn(calls=[ToolCall(id="area-1", name="query_area_status",
                                 arguments=json.dumps({"area_id": "area-001"}))]),
        AnalysisFailure("model_timeout"),
    ])
    report = await scenario(model, tmp_path)
    assert report["stop_reason"] == "model_timeout"
    assert report["results"][0]["facts"] == {"status": "restricted"}


async def test_overall_deadline_cancels_model(tmp_path):
    from anlan.workflows.tool_loop import LoopLimits

    class Slow:
        mode = "scripted_double"

        async def next(self, messages, run_id):
            await asyncio.sleep(10)

    report = await scenario(Slow(), tmp_path, limits=LoopLimits(timeout_seconds=0.01))
    assert report["stop_reason"] == "loop_timeout"
    assert report["results"] == []


async def test_unauthorized_task_never_calls_model(tmp_path):
    from anlan.workflows.tool_loop import check_facts_agent
    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)
    with pytest.raises(AccessDenied):
        await check_facts_agent(service, Identity(tenant_id="other", user_id="other"),
                               state["task_id"], REFS, tools(), SequenceModel([]), JsonlTrace())


async def test_loop_timeout_records_already_reserved_http_attempt(tmp_path):
    import httpx
    from test_tool_model import FakeLedger

    from anlan.llm.config import ModelConfig
    from anlan.llm.tool_model import DeepSeekToolModel
    from anlan.workflows.tool_loop import LoopLimits

    ledger = FakeLedger()

    async def slow(request):
        await asyncio.sleep(10)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        report = await scenario(DeepSeekToolModel(ModelConfig(api_key="test"), client, ledger),
                                tmp_path, limits=LoopLimits(timeout_seconds=0.05))
    assert report["stop_reason"] == "loop_timeout"
    assert report["requests_this_run"] == len(ledger.attempts) == 1
    assert report["model_attempts"][0]["attempt_id"] == "1"
    assert report["model_attempts"][0]["usage"] is None
    assert ledger.attempts[0]["status"] == "reserved"
