"""模型选择动作，宿主限定对象/权限/预算；所有结果只进入独立证据包。"""

import asyncio
import json
from time import perf_counter
from uuid import uuid4

from pydantic import Field, ValidationError

from anlan.analysis import AnalysisFailure
from anlan.contracts import Identity, StrictModel
from anlan.service import WorkflowService
from anlan.tool_model import SYSTEM_PROMPT
from anlan.tools.contracts import AreaQuery, FactReferences, WorkerQuery
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace


class LoopLimits(StrictModel):
    max_model_steps: int = Field(default=3, ge=1, le=3, strict=True)
    max_tool_calls: int = Field(default=4, ge=1, le=4, strict=True)
    timeout_seconds: float = Field(default=75, gt=0, le=75)


async def check_facts_agent(service: WorkflowService, identity: Identity, task_id: str,
                            references: dict, tools: FactTools, model, trace: JsonlTrace, *,
                            limits: LoopLimits | None = None) -> dict:
    snapshot = await service.get(identity, task_id)
    refs = FactReferences.model_validate(references)
    limits = limits or LoopLimits()
    started = perf_counter()
    report = {
        "schema_version": "fact-agent-evidence-v1", "data_origin": "SYNTHETIC",
        "mode": model.mode, "task_id": snapshot["task_id"],
        "correlation_id": snapshot["correlation_id"], "revision": snapshot["revision"],
        "source_run_id": snapshot["run_id"], "source_material_status": snapshot["status"],
        "run_id": str(uuid4()), "status": "awaiting_review", "results": [],
        "model_steps": 0, "tool_calls": 0, "model_attempts": [], "requests_this_run": 0,
        "summary": None, "summary_status": "not_available", "stop_reason": None,
        "trace_warning": None, "limits": limits.model_dump(),
        "notice": "合成事实与模型候选分别呈现，需人工复核；不是作业批准或合规结论。",
    }
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content":
        json.dumps({"data_origin": "SYNTHETIC", "materials": snapshot["fields"],
                    "references": refs.model_dump()}, ensure_ascii=False)}]
    allowed = {
        "query_worker_qualification": (WorkerQuery, tools.query_worker_qualification,
                                       {"worker_id": refs.worker_id,
                                        "qualification_type": refs.qualification_type}),
        "query_area_status": (AreaQuery, tools.query_area_status, {"area_id": refs.area_id}),
    }
    seen_ids = set()

    def emit(event, **details):
        if not trace.emit(event, report, source_run_id=report["source_run_id"], **details):
            report["trace_warning"] = "trace_write_failed"

    async def run_loop():
        for step in range(1, limits.max_model_steps + 1):
            report["model_steps"] = step
            try:
                turn = await model.next(messages, report["run_id"])
            except AnalysisFailure as exc:
                gateway = getattr(model, "gateway", None)
                attempt_id = gateway.last_attempt_id if gateway else None
                report["model_attempts"].append({"step": step, "attempt_id": attempt_id,
                                                 "error": exc.category, "usage": exc.usage})
                emit("model_step_finished", step=step, attempt_id=attempt_id,
                     error=exc.category, usage=exc.usage)
                return exc.category
            report["model_attempts"].append({"step": step, "attempt_id": turn.attempt_id,
                                             "error": None, "usage": turn.usage})
            emit("model_step_finished", step=step, attempt_id=turn.attempt_id,
                 error=None, usage=turn.usage)
            if perf_counter() - started >= limits.timeout_seconds:
                return "loop_timeout"
            if turn.final is not None:
                actual = {r["call_id"]: r["tool"] for r in report["results"] if r["executed"]}
                if set(actual.values()) != set(allowed):
                    return "missing_evidence"
                citations = turn.final.evidence_call_ids
                if (len(citations) != len(set(citations)) or not set(citations) <= actual.keys()
                        or {actual[c] for c in citations} != set(allowed)):
                    return "unsupported_citation"
                report["summary"] = turn.final.model_dump()
                report["summary_status"] = "unverified_candidate"
                return "completed"
            if not turn.calls:
                return "invalid_output"
            ids = [call.id for call in turn.calls]
            if len(ids) != len(set(ids)) or seen_ids.intersection(ids):
                return "duplicate_call_id"
            seen_ids.update(ids)
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": call.id, "type": "function", "function": {
                    "name": call.name, "arguments": call.arguments}} for call in turn.calls]})
            for call in turn.calls:
                if report["tool_calls"] >= limits.max_tool_calls:
                    return "tool_budget_exceeded"
                report["tool_calls"] += 1
                reason = None
                if call.name not in allowed:
                    reason = "tool_not_allowed"
                else:
                    schema, query, expected = allowed[call.name]
                    try:
                        parameters = schema.model_validate_json(call.arguments).model_dump()
                    except (ValueError, ValidationError):
                        reason = "invalid_parameters"
                    else:
                        if parameters != expected:
                            reason = "outside_references"
                if reason:
                    observation = {"tool": call.name, "outcome": "error", "reason": reason,
                                   "facts": None, "source": None, "executed": False}
                else:
                    result = await query(identity, parameters)
                    observation = {**result.model_dump(mode="json"), "executed": True}
                observation["call_id"] = call.id
                report["results"].append(observation)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(observation, ensure_ascii=False)})
                emit("agent_tool_finished", call_id=call.id, tool=call.name,
                     outcome=observation["outcome"], reason=observation["reason"],
                     executed=observation["executed"], source=observation["source"])
        return "step_budget_exceeded"

    try:
        async with asyncio.timeout(limits.timeout_seconds):
            report["stop_reason"] = await run_loop()
    except TimeoutError:
        report["stop_reason"] = "loop_timeout"
    gateway = getattr(model, "gateway", None)
    pending_id = gateway.last_attempt_id if gateway else None
    if pending_id and pending_id not in {a["attempt_id"] for a in report["model_attempts"]}:
        report["model_attempts"].append({
            "step": report["model_steps"], "attempt_id": pending_id,
            "error": "loop_timeout", "attempt_status": "reserved_unknown", "usage": None,
        })
        emit("model_step_finished", step=report["model_steps"], attempt_id=pending_id,
             error="loop_timeout", attempt_status="reserved_unknown", usage=None)
    report["requests_this_run"] = sum(bool(a["attempt_id"]) for a in report["model_attempts"])
    # 循环中途取消时，已占但尚未返回的调用由共享账本保留，不虚构其用量。
    report["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
    emit("tool_loop_finished", stop_reason=report["stop_reason"],
         model_steps=report["model_steps"], tool_calls=report["tool_calls"])
    return report
