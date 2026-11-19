"""Validate native payloads and required boundary events, beyond trace outer IDs."""

from typing import Literal

from .contracts import Contract, Text


class TraceEnvelope(Contract):
    eval_run_id: Text
    case_run_id: Text
    case_id: Text
    producer: Literal["native", "evaluation_runner"]
    payload: dict


def verify_trace(observation, traces):
    records = [TraceEnvelope.model_validate(row) for row in traces]
    events = [row.payload for row in records if row.producer == "evaluation_runner"]
    if (
        records[0].producer != "evaluation_runner"
        or events[0] != {"event": "case_started", "family": observation.family}
        or records[-1].producer != "evaluation_runner"
        or events[-1]
        != {
            "event": "case_finished",
            "loop_run_id": observation.loop_run_id,
            "exception": observation.exception,
        }
        or sum(e.get("event") == "case_started" for e in events) != 1
        or sum(e.get("event") == "case_finished" for e in events) != 1
    ):
        raise ValueError("missing or invalid trace boundaries")
    native_events = [row.payload for row in records if row.producer == "native"]
    if observation.family == "governance":
        decisions = [e for e in events if e.get("event") == "governance_decision"]
        if (
            native_events
            or len(decisions) != 1
            or decisions[0] != {"event": "governance_decision", **(observation.native or {})}
        ):
            raise ValueError("missing or mismatched governance trace")
        return
    integrity = [c for c in observation.calls if c.get("kind") == "state_integrity"]
    if len(integrity) != 1:
        raise ValueError("missing native state binding")
    baseline = integrity[0]
    analysis = [e for e in native_events if e.get("event") == "analysis_finished"]
    if len(analysis) != 1 or analysis[0].get("run_id") != baseline["source_run_id"]:
        raise ValueError("analysis trace run mismatch")
    for event in native_events:
        if any(
            event.get(key) != baseline[key] for key in ("task_id", "correlation_id", "revision")
        ) or event.get("event") not in {
            "analysis_finished",
            "model_step_finished",
            "agent_tool_finished",
            "tool_loop_finished",
        }:
            raise ValueError("native trace identity/event mismatch")
    if observation.exception == "AccessDenied":
        if (
            events
            != [
                {"event": "case_started", "family": "fact_loop"},
                {"event": "native_access_denied"},
                {"event": "case_finished", "loop_run_id": None, "exception": "AccessDenied"},
            ]
            or len(native_events) != 1
        ):
            raise ValueError("invalid pre-entry denial trace")
        return
    native = observation.native
    if native is None and observation.runner_errors:
        return  # Preserve explicit unexpected native failures without inventing terminal events.
    if native is None:
        raise ValueError("missing native loop report")
    loop_events = [e for e in native_events if e.get("event") != "analysis_finished"]
    if any(
        e.get("run_id") != native["run_id"] or e.get("source_run_id") != native["source_run_id"]
        for e in loop_events
    ):
        raise ValueError("native loop trace binding mismatch")
    finished = [e for e in loop_events if e["event"] == "tool_loop_finished"]
    models = [e for e in loop_events if e["event"] == "model_step_finished"]
    tools = [e for e in loop_events if e["event"] == "agent_tool_finished"]
    if (
        len(finished) != 1
        or finished[0].get("stop_reason") != native["stop_reason"]
        or finished[0].get("model_steps") != native["model_steps"]
        or finished[0].get("tool_calls") != native["tool_calls"]
        or len(models) != native["model_steps"]
        or len(tools) != len(native["results"])
    ):
        raise ValueError("incomplete native loop events")
    for event, result in zip(tools, native["results"]):
        if any(
            event.get(key) != result.get(key)
            for key in ("call_id", "tool", "outcome", "reason", "executed", "source")
        ):
            raise ValueError("native tool trace mismatch")
    if len(models) != len(native["model_attempts"]):
        raise ValueError("model attempt trace count mismatch")
    for event, attempt in zip(models, native["model_attempts"]):
        if any(
            event.get(key) != attempt.get(key) for key in ("step", "attempt_id", "error", "usage")
        ):
            raise ValueError("native model attempt trace mismatch")
    turns = [c for c in observation.calls if c.get("kind") == "scripted_turn"]
    if len(turns) != observation.counts.model or any(
        turn.get("run_id") != native["run_id"] for turn in turns
    ):
        raise ValueError("scripted-turn run mismatch")
