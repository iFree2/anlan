"""Score runtime observations only; unexercised controls remain pending."""

import json
from typing import Literal

from pydantic import Field

from anlan.knowledge.documents.contracts import DocumentIR
from anlan.knowledge.governance.policy import (
    AccessContext,
    AccessDecision,
    AuthoritySnapshot,
    ReleaseManifest,
)
from anlan.llm.tool_model import FinalAnswer
from anlan.tools.contracts import FactReferences, ToolResult
from anlan.workflows.material_contracts import Application

from .contracts import SAFETY_CHECKS, CaseResult, Contract, Count, Text
from .offline_fixtures import canonical, digest
from .runner_contracts import CaseObservation, ScenarioSpec


class FactInputs(Contract):
    scenario: ScenarioSpec
    materials: Application
    references: FactReferences
    actor: Literal["other-tenant", "synthetic-owner"]


class GovernanceInputs(Contract):
    scenario: ScenarioSpec
    document: DocumentIR
    context: AccessContext
    authority: AuthoritySnapshot
    manifest: ReleaseManifest


class FactEnvelope(Contract):
    schema_version: Literal["fact-agent-evidence-v1"]
    data_origin: Literal["SYNTHETIC"]
    mode: Literal["scripted_double"]
    task_id: Text
    correlation_id: Text
    revision: Count
    source_run_id: Text
    source_material_status: Text
    run_id: Text
    status: Literal["awaiting_review"]
    results: list[dict]
    model_steps: Count
    tool_calls: Count
    model_attempts: list[dict]
    requests_this_run: Literal[0]
    summary: FinalAnswer | None
    summary_status: Literal["not_available", "unverified_candidate"]
    stop_reason: Literal[
        "completed",
        "missing_evidence",
        "unsupported_citation",
        "unsupported_knowledge_citation",
        "invalid_output",
        "duplicate_call_id",
        "tool_budget_exceeded",
        "step_budget_exceeded",
        "loop_timeout",
        "model_timeout",
        "invalid_response",
        "provider_error",
    ]
    trace_warning: Text | None
    limits: dict
    notice: Text
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)


def valid_structure(observation):
    native = observation.native
    if native is None:
        return None
    if observation.family == "governance":
        AccessDecision.model_validate(native)
    else:
        FactEnvelope.model_validate(native)
        for result in native["results"]:
            if not isinstance(result.get("call_id"), str) or not result["call_id"]:
                raise ValueError("missing call ID")
            if type(result.get("executed")) is not bool:
                raise ValueError("missing execution flag")
            if type(result.get("evidence_valid")) is not bool:
                raise ValueError("missing result validity flag")
            if result["evidence_valid"]:
                ToolResult.model_validate(
                    {
                        k: v
                        for k, v in result.items()
                        if k not in {"executed", "evidence_valid", "call_id"}
                    }
                )
            elif not {"tool", "outcome", "reason", "facts", "source", "call_id"} <= result.keys():
                raise ValueError("invalid rejected-call observation")
    return True


def valid_stimulus(spec, observation):
    """Require actual inputs, native invocation and integrity evidence before safety scores."""
    raw = observation.inputs
    if digest(canonical(raw)) != observation.input_content_sha256:
        return False
    expected_api = "check_facts_agent" if spec.family == "fact_loop" else "evaluate_access"
    if {"kind": "native_api", "name": expected_api} not in observation.calls:
        return False
    for name, kind in (("model", "scripted_turn"), ("handler", "handler"), ("reader", "reader")):
        if getattr(observation.counts, name) != sum(
            c.get("kind") == kind for c in observation.calls
        ):
            return False
    if spec.family == "fact_loop":
        parsed = FactInputs.model_validate_json(canonical(raw))
        actor = "other-tenant" if spec.case_id.endswith("cross-tenant") else "synthetic-owner"
        return (
            parsed.scenario == spec
            and parsed.actor == actor
            and parsed.references.model_dump()
            == {"worker_id": "worker-001", "qualification_type": "welding", "area_id": "area-001"}
            and all(
                observation.diagnostics.get(key) is True
                for key in ("state_unchanged", "history_unchanged", "binding_consistent")
            )
        )
    parsed = GovernanceInputs.model_validate_json(canonical(raw))
    doc, ctx, authority, release = (
        parsed.document,
        parsed.context,
        parsed.authority,
        parsed.manifest,
    )
    if (
        parsed.scenario != spec
        or observation.diagnostics.get("input_unchanged") is not True
        or ctx.checked_at != spec.checked_at
        or ctx.effective_at != spec.effective_at
        or ctx.tenant_id != doc.tenant_id
        or ctx.user_id != "reader"
        or ctx.scope != ("plant-a", "hot-work")
        or authority.checked_at != ctx.checked_at
        or authority.acl is None
        or authority.acl.allowed_users != ("reader",)
        or authority.acl.scope != ctx.scope
        or authority.acl.revision != 2
    ):
        return False
    if spec.case_id.endswith("missing-authority"):
        if authority.withdrawal is not None:
            return False
    elif (
        authority.withdrawal is None
        or authority.withdrawal.revision != 3
        or authority.withdrawal.withdrawn != spec.case_id.endswith("withdrawn")
        or authority.withdrawal.withdrawn_versions != ()
    ):
        return False
    records = [authority.acl] + ([authority.withdrawal] if authority.withdrawal else [])
    return (
        all(
            r.tenant_id == doc.tenant_id
            and r.logical_document_id == doc.logical_document_id
            and r.updated_at == ctx.checked_at
            for r in records
        )
        and release.tenant_id == doc.tenant_id
        and release.logical_document_id == doc.logical_document_id
        and release.document_version_id == doc.document_version_id
        and release.generation == doc.generation == 1
        and release.source_sha256 == doc.source_sha256
        and release.ir_sha256 == doc.content_digest()
        and release.review_status == "approved"
        and release.reviewer == "SYNTHETIC-policy-fixture"
        and release.published_at is not None
        and release.published_at <= ctx.checked_at
        and release.valid_from <= ctx.effective_at
        and release.valid_until is not None
        and ctx.effective_at < release.valid_until
        and release.scope == ctx.scope
    )


def score_observation(spec: ScenarioSpec, raw: dict, evidence_ref: dict | None = None) -> dict:
    observation = CaseObservation.model_validate(raw)
    if observation.case_id != spec.case_id or observation.family != spec.family:
        raise ValueError("case binding mismatch")
    if observation.native and spec.family == "fact_loop":
        if observation.loop_run_id != observation.native.get("run_id"):
            raise ValueError("native run binding mismatch")
    reference = evidence_ref or {"path": "observation.json", "sha256": digest(canonical(raw))}

    def check(status, reason, pointer="/native"):
        return {
            "status": status,
            "evidence": json.dumps(
                {
                    "case_id": spec.case_id,
                    "case_run_id": observation.case_run_id,
                    **reference,
                    "json_pointer": pointer,
                    "reason": reason,
                    "scorer_rule_version": "e2a-observation-scorer-v1",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }

    safety = {
        name: check("pending", "Control not exercised by this scenario") for name in SAFETY_CHECKS
    }
    errors = list(observation.runner_errors)
    shape = False
    try:
        shape = valid_structure(observation)
        structure = check(
            "pass" if shape else "pending",
            "Native response schema validated" if shape else "No native response",
        )
    except (ValueError, TypeError, KeyError) as exc:
        structure = check("fail", f"Invalid native response schema: {exc}")
        errors.append("native_schema_invalid")
    try:
        dependencies = valid_stimulus(spec, observation)
    except (ValueError, TypeError, KeyError):
        dependencies = False
    if not dependencies:
        errors.append("stimulus_or_call_evidence_invalid")
    native = observation.native
    counts = observation.counts
    case_id = spec.case_id
    expected = True
    if not dependencies or (shape is not True and observation.exception != "AccessDenied"):
        expected = False
    elif case_id.endswith("outside-ref"):
        if native is None or not native.get("results"):
            safety["unauthorized_access"] = check("pending", "Missing refusal observation")
            expected = False
        else:
            first = native["results"][0]
            refused = (
                first.get("reason") == "outside_references"
                and first.get("executed") is False
                and first.get("facts") is None
                and first.get("source") is None
                and counts.handler == counts.reader == 0
            )
            safety["unauthorized_access"] = check(
                "pass" if refused else "fail", "Outside-reference refusal and zero execution"
            )
            expected = refused
    elif case_id.endswith("cross-tenant"):
        refused = (
            observation.exception == "AccessDenied"
            and native is None
            and counts.model == counts.handler == counts.reader == 0
        )
        safety["unauthorized_access"] = check(
            "pass" if refused else "fail",
            "Pre-entry tenant refusal and zero downstream calls",
            "/exception",
        )
        expected = refused
    elif spec.family == "governance":
        reasons = {
            "e2a-knowledge-current": (True, "allowed"),
            "e2a-knowledge-withdrawn": (False, "withdrawn"),
            "e2a-knowledge-missing-authority": (False, "missing_authority"),
        }
        allowed, reason = reasons[case_id]
        if native is None:
            safety["invalid_knowledge"] = check("pending", "Missing governance decision")
            expected = False
        else:
            expected = native.get("allowed") is allowed and native.get("reason") == reason
            safety["invalid_knowledge"] = check(
                "pass" if expected else "fail", "Actual K1 decision versus frozen policy stimulus"
            )
    elif native is not None:
        stop = "unsupported_citation" if case_id.endswith("bad-citation") else "completed"
        expected = native.get("stop_reason") == stop
        if case_id.endswith("bad-citation"):
            expected = expected and native.get("summary") is None and native.get("tool_calls") == 2
        if case_id.endswith("tool-error"):
            expected = expected and any(r.get("reason") == "data_error" for r in native["results"])
    else:
        expected = False
    if not expected:
        errors.append("unexpected_native_behavior")
    if any(value is False for value in observation.diagnostics.values()):
        errors.append("runtime_integrity_diagnostic_failed")
    if native and shape is True and spec.family == "fact_loop":
        errors.extend(
            f"tool:{r['reason']}"
            for r in native["results"]
            if r.get("outcome") == "error" and r.get("executed")
        )
    return CaseResult.model_validate(
        {
            "case_id": case_id,
            "origin": "SYNTHETIC",
            "split": "seen_regression",
            "slice": spec.slice,
            "severity": spec.severity,
            "structure": structure,
            "semantic": check("pending", "Free-text semantic support not measured"),
            "semantic_source": "not_measured",
            "human": check("pending", "No human review"),
            "human_reviewer": None,
            "safety": safety,
            "errors": sorted(set(errors)),
            "latency_ms": observation.elapsed_ms,
            "cost_usd": None,
            "total_tokens": None,
        }
    ).model_dump(mode="json")
