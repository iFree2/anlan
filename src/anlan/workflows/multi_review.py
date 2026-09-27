"""Two bounded model roles and a deterministic coordinator; never grants approval."""

import asyncio
import copy
from time import perf_counter
from uuid import uuid4

from pydantic import Field

from anlan.common.models import StrictModel
from anlan.context.assembly import ContextBudgetExceeded
from anlan.llm.contracts import AnalysisFailure
from anlan.llm.evidence_review import (
    WORK_PACKAGE,
    EvidenceReview,
    build_audit_context,
    validate_audit,
)
from anlan.workflows.review import synthesize


class ReviewLimits(StrictModel):
    model_steps: int = Field(default=2, ge=0, le=2, strict=True)
    timeout_seconds: float = Field(default=45, gt=0, le=60)


async def multi_review(bundle, risk_model, audit_model, *, limits=None, cancel_event=None,
                       trace=None, run_id=None, work_package=WORK_PACKAGE):
    if work_package not in {WORK_PACKAGE, "P6-WP03"}:
        raise ValueError("Unsupported multi-role work package")
    for model in (risk_model, audit_model):
        gateway = getattr(model, "gateway", None)
        if gateway and gateway.work_package != work_package:
            raise ValueError(f"Multi-role requests require trusted {work_package} package")
    limits = limits or ReviewLimits()
    started = perf_counter()
    deadline = started + limits.timeout_seconds
    snapshot = bundle["snapshot"]
    report = {"schema_version": "multi-review-v1", "data_origin": "SYNTHETIC",
              "mode": "bounded_risk_evidence_roles", "work_package": work_package,
              "run_id": run_id or str(uuid4()), "task_id": snapshot["task_id"],
              "revision": snapshot["revision"], "source_run_id": snapshot["run_id"],
              "correlation_id": snapshot.get("correlation_id", snapshot["task_id"]),
              "status": "awaiting_review", "observations": copy.deepcopy(bundle["observations"]),
              "collection": copy.deepcopy(bundle.get("collection")),
              "risk": None, "candidate": None, "audit": None, "rejected_audit": None,
              "audit_context": None, "children": [], "model_steps": 0, "requests_this_run": 0,
              "model_step_budget": limits.model_steps, "deadline_seconds": limits.timeout_seconds,
              "stop_reason": None, "coordination": "review_unavailable_requires_human_review",
              "warnings": list(bundle["warnings"]),
              "notice": "两角色模型候选与证据复核仍需人工决定；不是作业批准。"}

    def stopped():
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled"
        if perf_counter() >= deadline:
            return "parent_deadline_exceeded"
        if report["model_steps"] >= limits.model_steps:
            return "parent_model_budget_exceeded"
        return None

    async def step(role, model, operation):
        reason = stopped()
        if reason:
            report["stop_reason"] = reason
            return None
        child = {"role": role, "run_id": report["run_id"] + ":" + role,
                 "parent_run_id": report["run_id"], "revision": snapshot["revision"],
                 "source_run_id": snapshot["run_id"], "mode": model.mode,
                 "attempt_id": None, "usage": None, "stop_reason": None}
        report["children"].append(child)
        report["model_steps"] += 1
        gateway = getattr(model, "gateway", None)
        old_attempt = gateway.last_attempt_id if gateway else None
        child_started = perf_counter()
        task = asyncio.create_task(operation(child["run_id"]))
        watcher = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
        try:
            done, _ = await asyncio.wait({task} | ({watcher} if watcher else set()),
                                         timeout=max(0, deadline - perf_counter()),
                                         return_when=asyncio.FIRST_COMPLETED)
            if watcher in done or not done or perf_counter() >= deadline:
                reason = "cancelled" if watcher in done else "parent_deadline_exceeded"
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                report["stop_reason"] = child["stop_reason"] = reason
                return None
            result = task.result()
            child.update(attempt_id=result.get("attempt_id"), usage=result.get("usage"),
                         stop_reason=result.get("stop_reason", "completed"))
            return result
        except AnalysisFailure as exc:
            report["stop_reason"] = child["stop_reason"] = exc.category
            child["usage"] = exc.usage
            return None
        except Exception:
            report["stop_reason"] = child["stop_reason"] = "role_error"
            return None
        finally:
            for job in (task, watcher):
                if job is not None and not job.done():
                    job.cancel()
            await asyncio.gather(task, *([watcher] if watcher else []), return_exceptions=True)
            if gateway and gateway.last_attempt_id != old_attempt:
                child["attempt_id"] = gateway.last_attempt_id
            child["elapsed_ms"] = round((perf_counter() - child_started) * 1000, 2)
            report["requests_this_run"] = sum(c["attempt_id"] is not None
                                               for c in report["children"])

    collection_stop = (bundle.get("collection") or {}).get("stop_reason", "completed")
    if collection_stop != "completed":
        report["stop_reason"] = "collection_" + collection_stop
    else:
        risk = await step("risk", risk_model, lambda child_id: synthesize(
            bundle, risk_model, trace=trace, run_id=child_id, work_package=work_package))
        if risk is not None:
            report["risk"] = risk
            report["candidate"] = risk["candidate"]
            if risk["stop_reason"] != "completed":
                report["stop_reason"] = risk["stop_reason"]
            else:
                try:
                    context = build_audit_context(risk["context"], risk["candidate"])
                except ContextBudgetExceeded:
                    report["stop_reason"] = "audit_context_budget_exceeded"
                else:
                    report["audit_context"] = context
                    audit = await step("evidence", audit_model,
                                       lambda child_id: audit_model.generate(context, child_id))
                    if audit is not None:
                        try:
                            value = validate_audit(EvidenceReview.model_validate(audit["review"]),
                                                   context)
                        except (ValueError, KeyError, TypeError):
                            report["rejected_audit"] = audit.get("review", audit)
                            report["stop_reason"] = "unsupported_audit"
                        else:
                            report["audit"] = value.model_dump()
                            report["coordination"] = (
                                "disputed_requires_human_review" if any(
                                    a.verdict != "supported" for a in value.assessments)
                                else "reviewed_candidate_requires_human_review")
                            report["stop_reason"] = "completed"
    report["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
    if trace is not None and not trace.emit("multi_review_finished", report,
            elapsed_ms=report["elapsed_ms"], mode=report["mode"],
            error=None if report["stop_reason"] == "completed" else report["stop_reason"],
            model_steps=report["model_steps"], requests_this_run=report["requests_this_run"]):
        report["warnings"].append(trace.warning)
    return report
