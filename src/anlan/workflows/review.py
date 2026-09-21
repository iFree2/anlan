"""Fixed read-only collection and one bounded model synthesis; never changes task state."""


import copy
import hashlib
from datetime import datetime
from importlib.resources import files
from time import perf_counter
from uuid import uuid4

from anlan.common.errors import InvalidTransition
from anlan.common.models import Identity
from anlan.context.assembly import ContextBudgetExceeded, build_context
from anlan.infrastructure.trace import JsonlTrace
from anlan.knowledge.tool import KnowledgeParameters, query_knowledge
from anlan.llm.contracts import AnalysisFailure
from anlan.workflows.facts import check_facts
from anlan.workflows.review_contracts import WORK_PACKAGE, ReviewCandidate, validate_candidate

GUIDANCE_VERSION = "hot-work-review-v1"


def guidance():
    text = files("anlan").joinpath("assets/hot-work-review-v1.md").read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


async def collect_review(service, identity, task_id, references, question, tools,
                         knowledge_store, memory_store, trace=None):
    started = perf_counter()
    snapshot = await service.get(identity, task_id)  # Authorize before all dependencies.
    KnowledgeParameters(question=question)
    trace = trace or JsonlTrace()
    facts = await check_facts(service, identity, task_id, references, tools, trace)
    knowledge = await query_knowledge(knowledge_store, identity, {"question": question})
    warnings = ["fact_" + facts["trace_warning"]] if facts.get("trace_warning") else []
    try:
        memories = await memory_store.list_active(identity)
    except Exception:
        memories = []
        warnings.append("memory_unavailable")
    current = await service.get(identity, task_id)
    if (current != snapshot or facts["revision"] != snapshot["revision"]
            or facts["source_run_id"] != snapshot["run_id"]):
        raise InvalidTransition("采集期间材料发生变化；需按当前版本重新核验")
    return {"identity": identity.model_dump(), "snapshot": snapshot,
            "observations": [*facts["results"], knowledge.model_dump(mode="json")],
            "question": question, "memories": memories, "warnings": warnings,
            "as_of": tools.clock().isoformat(),
            "collection_elapsed_ms": round((perf_counter() - started) * 1000, 2)}


async def synthesize(bundle, model, *, use_memory=True, use_knowledge=True, budget_bytes=24000,
                     trace=None, run_id=None, work_package=None):
    started = perf_counter()
    gateway = getattr(model, "gateway", None)
    actual_package = gateway.work_package if gateway else WORK_PACKAGE
    if gateway and work_package is not None and work_package != actual_package:
        raise ValueError("Report package must match the model gateway")
    work_package = work_package or actual_package
    snapshot = bundle["snapshot"]
    text, digest = guidance()
    report = {"schema_version": "single-review-v1", "data_origin": "SYNTHETIC",
              "mode": model.mode, "task_id": snapshot["task_id"], "revision": snapshot["revision"],
              "source_run_id": snapshot["run_id"], "run_id": run_id or str(uuid4()),
              "correlation_id": snapshot.get("correlation_id", snapshot["task_id"]),
              "observations": copy.deepcopy(bundle["observations"]),
              "warnings": list(bundle["warnings"]), "candidate": None, "rejected_candidate": None,
              "candidate_status": "not_available", "stop_reason": None, "context": None,
              "status": "awaiting_review", "trace_warning": None,
              "requests_this_run": 0, "attempt_id": None, "usage": None,
              "guidance_version": GUIDANCE_VERSION, "guidance_sha256": digest,
              "work_package": work_package,
              "notice": "固定只读采集＋单模型综合；结构校验不证明主张语义或批准。"}
    try:
        context = build_context(Identity.model_validate(bundle["identity"]), snapshot,
                                bundle["observations"], bundle["memories"],
                                now=datetime.fromisoformat(bundle["as_of"]),
                                budget_bytes=budget_bytes, use_memory=use_memory,
                                use_knowledge=use_knowledge, guidance=text,
                                question=bundle.get("question"))
        report["context"] = context
        result = await model.generate(context, report["run_id"])
        report.update(usage=result["usage"], attempt_id=result["attempt_id"])
        try:
            value = validate_candidate(ReviewCandidate.model_validate(result["candidate"]), context)
        except ValueError:
            report.update(rejected_candidate=result["candidate"], stop_reason="unsupported_output")
        else:
            report.update(candidate=value.model_dump(), candidate_status="unverified_candidate",
                          stop_reason="completed")
    except ContextBudgetExceeded:
        report["stop_reason"] = "context_budget_exceeded"
    except AnalysisFailure as exc:
        report.update(stop_reason=exc.category, usage=exc.usage)
        gateway = getattr(model, "gateway", None)
        report["attempt_id"] = gateway.last_attempt_id if gateway else None
    report["requests_this_run"] = int(report["attempt_id"] is not None)
    report["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
    if trace is not None:
        if not trace.emit(
                "review_finished", report, mode=report["mode"], elapsed_ms=report["elapsed_ms"],
                attempt_id=report["attempt_id"], usage=report["usage"],
                error=None if report["stop_reason"] == "completed" else report["stop_reason"]):
            report["trace_warning"] = trace.warning
    return report
