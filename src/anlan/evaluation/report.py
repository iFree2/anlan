"""Aggregate complete and missing evidence separately, with safety veto priority."""

import json
from pathlib import Path

from .contracts import SAFETY_CHECKS, Bundle


def evaluate_bundle(payload: dict) -> dict:
    bundle = Bundle.model_validate(payload)
    cases = bundle.cases
    missing = sorted(set(bundle.manifest.required_case_ids) - {row.case_id for row in cases})
    blockers, unmeasured = [], []
    safety_counts = {}
    for name in SAFETY_CHECKS:
        counts = {"pass": 0, "fail": 0, "pending": 0}
        for row in cases:
            check = row.safety.get(name)
            status = check.status if check else "pending"
            counts[status] += 1
            detail = {
                "case_id": row.case_id,
                "check": name,
                "evidence": check.evidence if check else "check record missing",
            }
            if status == "fail":
                blockers.append(detail)
            elif status == "pending":
                unmeasured.append(detail)
        safety_counts[name] = counts
    quality = {
        dimension: {
            status: sum(getattr(row, dimension).status == status for row in cases)
            for status in ("pass", "fail", "pending")
        }
        for dimension in ("structure", "semantic", "human")
    }
    legacy_issue_set = {
        status: sum(
            row.legacy_issue_set is not None and row.legacy_issue_set.status == status
            for row in cases
        )
        for status in ("pass", "fail", "pending")
    }
    errors = [{"case_id": row.case_id, "error": error} for row in cases for error in row.errors]
    failed = any(counts["fail"] for counts in quality.values()) or legacy_issue_set["fail"] > 0
    pending = any(counts["pending"] for counts in quality.values())
    # An uncalibrated Judge cannot authorize release even when its score says pass.
    judge_only = any(row.semantic_source == "judge" and row.human.status != "pass" for row in cases)
    gate = (
        "blocked"
        if blockers or failed or errors
        else "pending"
        if (
            missing
            or not cases
            or unmeasured
            or pending
            or judge_only
            or bundle.manifest.fixed_at is None
        )
        else "pass"
    )
    latency = sorted(row.latency_ms for row in cases if row.latency_ms is not None)
    complete_cases = bool(cases) and not missing
    complete_latency = complete_cases and len(latency) == len(cases)
    tokens = [row.total_tokens for row in cases if row.total_tokens is not None]
    costs = [row.cost_usd for row in cases if row.cost_usd is not None]

    def percentile(fraction):
        if not complete_latency:
            return None
        # Nearest rank, explicitly scoped to complete case measurements.
        from math import ceil

        return latency[max(0, ceil(len(latency) * fraction) - 1)]

    return {
        "schema_version": "enterprise-report-v2",
        "manifest": bundle.manifest.model_dump(mode="json"),
        "gate": gate,
        "coverage": {
            "required_cases": len(bundle.manifest.required_case_ids),
            "observed_cases": len(cases),
            "missing_case_ids": missing,
        },
        "safety": {"checks": safety_counts, "blockers": blockers, "unmeasured": unmeasured},
        "quality": quality,
        "legacy_metrics": {"issue_set": legacy_issue_set},
        "reliability": {
            "errors": errors,
            "latency_measured_cases": len(latency),
            "latency_ms_p50": percentile(0.50),
            "latency_ms_p95": percentile(0.95),
            "latency_method": "nearest_rank_all_cases_or_null",
        },
        "cost": {
            "total_tokens": sum(tokens) if complete_cases and len(tokens) == len(cases) else None,
            "known_tokens": sum(tokens) if tokens else None,
            "token_measured_cases": len(tokens),
            "total_cost_usd": sum(costs) if complete_cases and len(costs) == len(cases) else None,
            "known_cost_usd": sum(costs) if costs else None,
            "cost_measured_cases": len(costs),
        },
        "cases": [row.model_dump(mode="json") for row in cases],
        "provenance": bundle.provenance.model_dump(mode="json") if bundle.provenance else None,
        "limitations": [
            "Finite seen regression evidence only; no unseen or enterprise certification.",
            "Recorded assertions require trusted scorers; this aggregator is not a judge.",
        ],
    }


def write_report(path: str | Path, report: dict) -> None:
    """Create a separate artifact, never overwrite historical evidence."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
