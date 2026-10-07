"""One bounded synthesis step preserving raw events and successful collection evidence."""

import asyncio
import copy
from time import perf_counter

from anlan.context.assembly import ContextBudgetExceeded
from anlan.llm.contracts import AnalysisFailure
from anlan.workflows.perception_contracts import WORK_PACKAGE, build_context, validate_candidate


async def generate_bounded(model, context, run_id, cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        return None
    job = asyncio.create_task(model.generate(context, run_id))
    signal = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
    jobs = [job, signal] if signal else [job]
    try:
        await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        if cancel_event is not None and cancel_event.is_set():
            return None
        return await job
    finally:
        for child in jobs:
            if not child.done():
                child.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


async def synthesize_perception(
    event, bundle, model, run_id, *, timeout_seconds=20, cancel_event=None
):
    if not 0 < timeout_seconds <= 20:
        raise ValueError("Perception model deadline must be within 20 seconds")
    started = perf_counter()
    from anlan.infrastructure.budget import CONSOLE_WORK_PACKAGE
    gateway = getattr(model, "gateway", None)
    package = gateway.work_package if gateway else WORK_PACKAGE
    if package not in {WORK_PACKAGE, CONSOLE_WORK_PACKAGE}:
        raise ValueError("Perception model gateway must use an authorized host package")
    result = {
        "schema_version": "perception-review-v1",
        "work_package": package,
        "mode": model.mode,
        "run_id": run_id,
        "event": copy.deepcopy(event),
        "observations": copy.deepcopy(bundle["observations"]),
        "collection": copy.deepcopy(bundle.get("collection")),
        "candidate": None,
        "rejected_candidate": None,
        "context": None,
        "attempt_id": None,
        "usage": None,
        "model_steps": 0,
        "requests_this_run": 0,
        "stop_reason": "not_started",
        "output_diagnostics": None,
    }
    stop = bundle.get("collection", {}).get("stop_reason", "completed")
    if stop != "completed":
        result["stop_reason"] = stop
        return result
    try:
        context = build_context(event, bundle)
        result["context"] = context
        result["model_steps"] = 1
        async with asyncio.timeout(timeout_seconds):
            generated = await generate_bounded(model, context, run_id, cancel_event)
        if generated is None or (cancel_event is not None and cancel_event.is_set()):
            result["stop_reason"] = "cancelled"
            return result
        result.update(attempt_id=generated["attempt_id"], usage=generated["usage"])
        try:
            result["candidate"] = validate_candidate(generated["candidate"], context)
        except ValueError:
            result.update(
                rejected_candidate=generated["candidate"], stop_reason="unsupported_output"
            )
        else:
            result["stop_reason"] = "completed"
    except ContextBudgetExceeded:
        result["stop_reason"] = "context_budget_exceeded"
    except TimeoutError:
        result["stop_reason"] = "model_timeout"
    except AnalysisFailure as exc:
        result.update(stop_reason=exc.category, usage=exc.usage)
    except Exception:
        result["stop_reason"] = "model_unavailable"
    finally:
        if gateway and hasattr(model, "attempt_for"):
            result["attempt_id"] = result["attempt_id"] or model.attempt_for(run_id)
            result["output_diagnostics"] = model.diagnostics_for(run_id)
        result["requests_this_run"] = int(result["attempt_id"] is not None)
        result["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
    return result
