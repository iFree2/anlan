"""Fixed, scoped read-only branches. No model autonomy or shared Graph writes."""

import asyncio
import copy
from datetime import datetime
from time import perf_counter
from uuid import uuid4

from pydantic import Field

from anlan.contracts import StrictModel
from anlan.knowledge_tool import KnowledgeObservation, KnowledgeParameters, query_knowledge
from anlan.registry import InvalidTransition
from anlan.tools.contracts import FactReferences, ToolResult

WORK_PACKAGE = "P4-WP01"


class CollectionLimits(StrictModel):
    tool_calls: int = Field(default=3, ge=0, le=3, strict=True)
    timeout_seconds: float = Field(default=10, gt=0, le=30)


def canonical_observations(observations):
    """Ignore measured duration only; retain time, values and all source metadata."""
    return [{k: copy.deepcopy(v) for k, v in o.items() if k != "elapsed_ms"}
            for o in observations]


def unknown(tool, object_id, now, reason):
    return {"data_origin": "SYNTHETIC", "tool": tool, "object_id": object_id,
            "queried_at": now.isoformat(), "outcome": "error", "reason": reason,
            "facts": None, "source": [] if tool == "query_knowledge" else None,
            "message": "本次证据未知，需人工复核；不是作业批准。", "elapsed_ms": 0,
            **({"citations": []} if tool == "query_knowledge" else {})}


def source_conflicts(observations):
    """Keep contradictory provenance explicit; never choose by completion order."""
    seen, conflicts, indices = {}, [], set()
    for index, observation in enumerate(observations):
        source = observation.get("source")
        entries = []
        if isinstance(source, dict):
            entries.append((("resource", source["resource"]),
                            (source["version"], source["sha256"])))
        for citation in observation.get("citations", []):
            entries.extend([
                (("document", citation["doc_id"]),
                 (citation["version"], citation["document_hash"])),
                (("chunk", citation["chunk_id"]),
                 (citation["content_hash"], citation["quote"])),
            ])
        for key, value in entries:
            previous = seen.get(key)
            if previous is not None and previous[0] != value:
                indices.update([previous[1], index])
                conflicts.append({"kind": key[0], "source_id": key[1],
                                  "observation_indices": sorted({previous[1], index})})
            else:
                seen[key] = (value, index)
    return conflicts, indices


async def collect_parallel(service, identity, task_id, references, question, tools,
                           knowledge_store, memory_store, *, parallel=True, limits=None,
                           cancel_event=None, trace=None):
    snapshot = copy.deepcopy(await service.get(identity, task_id))
    # Authorization deliberately precedes clocks, parameters and all other dependencies.
    limits = limits or CollectionLimits()
    refs = FactReferences.model_validate(references)
    query = KnowledgeParameters(question=question)
    identity = identity.model_copy(deep=True)
    now = tools.clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone required")
    tools, knowledge_store, memory_store = (copy.copy(value)
                                           for value in (tools, knowledge_store, memory_store))
    tools.clock = knowledge_store.clock = memory_store.clock = lambda: now
    started = perf_counter()
    deadline = started + limits.timeout_seconds
    run_id = str(uuid4())
    stop = None
    results, calls = {}, []
    metadata = {"task_id": snapshot["task_id"], "revision": snapshot["revision"],
                "source_run_id": snapshot["run_id"], "identity": identity.model_dump(),
                "as_of": now.isoformat()}
    children = [{"role": role, "run_id": str(uuid4()), "parent_run_id": run_id,
                 "input": {**copy.deepcopy(metadata), "parameters": parameters},
                 "tool_budget": sum(i < limits.tool_calls for i in slots),
                 "tool_calls": 0, "deadline_seconds": limits.timeout_seconds}
                for role, parameters, slots in [
                    ("facts", refs.model_dump(), (0, 1)),
                    ("knowledge", query.model_dump(), (2,))]]
    specs = [
        ("query_worker_qualification", refs.worker_id,
         {"worker_id": refs.worker_id, "qualification_type": refs.qualification_type}),
        ("query_area_status", refs.area_id, {"area_id": refs.area_id}),
        ("query_knowledge", None, query.model_dump()),
    ]

    def stopped():
        if stop == "cancelled" or (cancel_event is not None and cancel_event.is_set()):
            return "parent_cancelled"
        if stop == "deadline_exceeded" or perf_counter() >= deadline:
            return "parent_deadline_exceeded"
        return None

    async def invoke(index, child):
        tool, object_id, parameters = specs[index]
        reason = stopped()
        if reason or index >= limits.tool_calls:
            results[index] = unknown(tool, object_id, now, reason or "parent_tool_budget_exceeded")
            return
        # Predistributed grants make total usage independent of branch scheduling.
        child["tool_calls"] += 1
        calls.append({"child_run_id": child["run_id"], "tool": tool, "index": index})
        try:
            if index == 2:
                value = await query_knowledge(knowledge_store, identity.model_copy(deep=True),
                                              parameters)
            else:
                value = await getattr(tools, tool)(identity.model_copy(deep=True), parameters)
            data = value.model_dump(mode="json")
            (KnowledgeObservation if index == 2 else ToolResult).model_validate(data)
            if (data["tool"] != tool or data["object_id"] != object_id
                    or datetime.fromisoformat(data["queried_at"]) != now):
                raise ValueError("result differs from trusted input")
            # Validate provenance structure before the fan-in conflict detector.
            source_conflicts([data])
        except asyncio.CancelledError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            data = unknown(tool, object_id, now, "branch_contract_conflict")
        except Exception:
            data = unknown(tool, object_id, now, "branch_tool_error")
        # A dependency may suppress cancellation or finish blocking work late.
        reason = stopped()
        results[index] = unknown(tool, object_id, now, reason) if reason else data

    async def facts():
        for index in (0, 1):
            await invoke(index, children[0])

    async def knowledge():
        await invoke(2, children[1])

    async def serial():
        await facts()
        await knowledge()

    tasks = [asyncio.create_task(fn(), name=f"{run_id}:{name}") for name, fn in (
        [("facts", facts), ("knowledge", knowledge)] if parallel else [("serial", serial)])]
    cancellation = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
    async def supervise(jobs):
        nonlocal stop
        pending = set(jobs)
        while pending:
            waiting = pending | ({cancellation} if cancellation else set())
            done, _ = await asyncio.wait(waiting, timeout=max(0, deadline - perf_counter()),
                                         return_when=asyncio.FIRST_COMPLETED)
            if cancellation in done:
                stop = "cancelled"
                break
            pending -= done
            if not done or perf_counter() >= deadline:
                stop = "deadline_exceeded"
                break
        if stop:
            for task in pending:
                task.cancel()
        # Child cancellation is a result; cancellation of this await by the caller still raises.
        await asyncio.gather(*jobs, return_exceptions=True)

    warnings, memories = [], []
    try:
        await supervise(tasks)
        if stopped():
            stop = "cancelled" if stopped() == "parent_cancelled" else "deadline_exceeded"
            warnings.append("memory_not_read_after_stop")
        else:
            memory_task = asyncio.create_task(memory_store.list_active(identity))
            tasks.append(memory_task)
            await supervise([memory_task])
            if stopped():
                stop = "cancelled" if stopped() == "parent_cancelled" else "deadline_exceeded"
                warnings.append("memory_not_read_after_stop")
            elif memory_task.cancelled() or memory_task.exception() is not None:
                warnings.append("memory_unavailable")
            else:
                memories = memory_task.result()
    finally:
        for task in tasks + ([cancellation] if cancellation else []):
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, *([cancellation] if cancellation else []),
                             return_exceptions=True)
    for index, (tool, object_id, _) in enumerate(specs):
        if index not in results:
            results[index] = unknown(tool, object_id, now, stopped() or "branch_tool_error")
    observations = [results[i] for i in range(3)]
    conflicts, indices = source_conflicts(observations)
    rejected = [{"index": i, "observation": copy.deepcopy(observations[i])}
                for i in sorted(indices)]
    for i in indices:
        observations[i] = unknown(specs[i][0], specs[i][1], now, "source_conflict")
    # Read-only safety finalization has a separate bounded 2s allowance. No child is live here.
    current = await asyncio.wait_for(service.get(identity, task_id), timeout=2)
    if current != snapshot:
        raise InvalidTransition("采集期间材料发生变化；拒绝混合版本")
    if cancel_event is not None and cancel_event.is_set():
        stop = "cancelled"
    elapsed = round((perf_counter() - started) * 1000, 2)
    collection = {"schema_version": "scoped-collection-v1", "work_package": WORK_PACKAGE,
                  "mode": "fixed_parallel_branches" if parallel else "fixed_serial_branches",
                  "run_id": run_id, "children": children, "calls": calls,
                  "tool_calls": len(calls), "tool_budget": limits.tool_calls,
                  "deadline_seconds": limits.timeout_seconds, "finalization_timeout_seconds": 2,
                  "stop_reason": stop or "completed", "conflicts": conflicts,
                  "rejected_observations": rejected, "elapsed_ms": elapsed,
                  "requests_this_run": 0, "material_unchanged": True}
    if trace is not None:
        state = {**snapshot, "run_id": run_id, "status": "awaiting_review"}
        for child in children:
            if not trace.emit("branch_finished", state, child_run_id=child["run_id"],
                              parent_run_id=run_id, role=child["role"],
                              tool_calls=child["tool_calls"], source_run_id=snapshot["run_id"],
                              mode=collection["mode"], error=stop):
                warnings.append(trace.warning)
    return {"identity": identity.model_dump(), "snapshot": snapshot, "question": question,
            "observations": observations, "memories": memories, "warnings": warnings,
            "as_of": now.isoformat(), "collection_elapsed_ms": elapsed,
            "collection": collection}
