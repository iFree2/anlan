"""Fixed read-only collection and one bounded model synthesis; never changes task state."""

import copy
import hashlib
import json
from datetime import datetime
from importlib.resources import files
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import Field

from anlan.analysis import AnalysisFailure
from anlan.context import ContextBudgetExceeded, build_context
from anlan.contracts import Identity, NonEmpty, StrictModel
from anlan.facts import check_facts
from anlan.knowledge_tool import KnowledgeParameters, query_knowledge
from anlan.model_gateway import ModelGateway
from anlan.registry import InvalidTransition
from anlan.tool_model import KnowledgeCitation
from anlan.trace import JsonlTrace

GUIDANCE_VERSION = "hot-work-review-v1"
WORK_PACKAGE = "P3-WP03"


def guidance():
    text = files("anlan").joinpath("assets/hot-work-review-v1.md").read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


class Claim(StrictModel):
    text: NonEmpty
    observation_ids: list[str] = Field(max_length=3)
    knowledge_citations: list[KnowledgeCitation] = Field(max_length=3)


class Presentation(StrictModel):
    detail_level: Literal["brief", "detailed"]
    presentation_order: Literal["unknowns_first", "sources_first"]


class ReviewCandidate(StrictModel):
    claims: list[Claim] = Field(min_length=1, max_length=6)
    unknown_observation_ids: list[str] = Field(max_length=3)
    presentation: Presentation
    notice: Literal["待人工复核；不是作业批准"]


def validate_candidate(candidate: ReviewCandidate, context: dict):
    data = json.loads(context["messages"][1]["content"])
    observations = {o["observation_id"]: o for o in data["observations"]}
    chunks = {c["chunk_id"]: c["quote"] for c in data["knowledge"]}
    unknown = {key for key, o in observations.items() if o["outcome"] != "ok"}
    if (set(candidate.unknown_observation_ids) != unknown
            or len(candidate.unknown_observation_ids) != len(unknown)):
        raise ValueError("Unknown observations must be preserved exactly")
    covered, cited = set(), set()
    for claim in candidate.claims:
        if not claim.observation_ids and not claim.knowledge_citations:
            raise ValueError("Each claim requires an observed source")
        if (not set(claim.observation_ids) <= observations.keys()
                or len(set(claim.observation_ids)) != len(claim.observation_ids)):
            raise ValueError("Invalid observation reference")
        covered.update(claim.observation_ids)
        for citation in claim.knowledge_citations:
            if (citation.chunk_id not in chunks or not citation.quote.strip()
                    or citation.quote not in chunks[citation.chunk_id]):
                raise ValueError("Citation is not in model-visible context")
            cited.add(citation.chunk_id)
    if covered != observations.keys() or (chunks and not cited):
        raise ValueError("Required evidence was omitted")
    return candidate


class DeepSeekReviewModel:
    mode = "deepseek_live"

    def __init__(self, config, client, ledger):
        self.gateway = ModelGateway(config, client, ledger, work_package=WORK_PACKAGE)

    async def generate(self, context, run_id):
        def parse(envelope):
            choice = envelope["choices"][0]
            message = choice["message"]
            if (choice["finish_reason"] != "stop" or message["role"] != "assistant"
                    or message.get("tool_calls")):
                raise ValueError("Expected a final synthesis")
            return ReviewCandidate.model_validate_json(message["content"])
        candidate, usage, attempt = await self.gateway.call({
            "model": self.gateway.config.model, "thinking": {"type": "disabled"},
            "temperature": 0, "max_tokens": 1024,
            "response_format": {"type": "json_object"}, "messages": context["messages"],
        }, parse, run_id)
        return {"candidate": candidate.model_dump(), "usage": usage, "attempt_id": attempt}


class ScriptedReviewModel:
    """Protocol double using visible observations, not model quality evidence."""
    mode = "scripted_double"

    async def generate(self, context, run_id):
        data = json.loads(context["messages"][1]["content"])
        claims = [{"text": f"SYNTHETIC替身：{o['tool']}={o['outcome']}/{o.get('reason')}",
                   "observation_ids": [o["observation_id"]], "knowledge_citations": []}
                  for o in data["observations"]]
        if data["knowledge"]:
            c = data["knowledge"][0]
            claims.append({"text": c["quote"][:180], "observation_ids": [],
                           "knowledge_citations": [{"chunk_id": c["chunk_id"],
                                                     "quote": c["quote"][:180]}]})
        presentation = {"detail_level": "brief", "presentation_order": "unknowns_first"}
        presentation.update({m["key"]: m["value"] for m in data["preferences"]})
        candidate = ReviewCandidate.model_validate({"claims": claims,
            "unknown_observation_ids": [o["observation_id"] for o in data["observations"]
                                        if o["outcome"] != "ok"],
            "presentation": presentation, "notice": "待人工复核；不是作业批准"})
        return {"candidate": candidate.model_dump(), "usage": None, "attempt_id": None}


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
                     trace=None, run_id=None):
    started = perf_counter()
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
              "work_package": WORK_PACKAGE,
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
