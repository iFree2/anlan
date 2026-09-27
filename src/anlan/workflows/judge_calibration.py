"""Verifiable finite calibration; labels never enter the model context."""

import copy
import hashlib
from datetime import datetime

from anlan.common.models import Identity
from anlan.context.assembly import build_context, encoded
from anlan.llm.evidence_review import EvidenceReview, build_audit_context, validate_audit

WORK_PACKAGE = "P6-WP03"
VERDICTS = ("supported", "unsupported", "uncertain")


def calibration_context(case, rubric):
    bundle = case["bundle"]
    risk = build_context(
        Identity.model_validate(bundle["identity"]), bundle["snapshot"],
        bundle["observations"], [], now=datetime.fromisoformat(bundle["as_of"]),
        question=bundle["question"],
    )
    context = build_audit_context(risk, case["judge_candidate"])
    context["messages"][0]["content"] += "\n本次固定评分口径：" + rubric
    raw = encoded(context["messages"]).encode()
    if len(raw) > 24000:
        raise ValueError("Calibration context exceeds bound")
    context.update(sha256=hashlib.sha256(raw).hexdigest(), bytes_used=len(raw))
    return context


def score_calibration(value, context, gold):
    if not gold or any(v not in VERDICTS for v in gold.values()):
        raise ValueError("Invalid calibration labels")
    matrix = {expected: {actual: 0 for actual in (*VERDICTS, "invalid")}
              for expected in VERDICTS}
    try:
        review = validate_audit(EvidenceReview.model_validate(value), context)
        predicted = {a.claim_id: a.verdict for a in review.assessments}
        if predicted.keys() != gold.keys():
            raise ValueError("Calibration claim identities differ")
    except ValueError:
        predicted = {key: "invalid" for key in gold}
    for key, label in gold.items():
        matrix[label][predicted[key]] += 1
    return {"correct": sum(predicted[k] == v for k, v in gold.items()),
            "total": len(gold), "invalid": sum(v == "invalid" for v in predicted.values()),
            "confusion": matrix, "gold": gold, "predicted": predicted,
            "label_origin": "ai_authored_verifiable_enum_facts_not_independent_human_gold"}


def ablate_audit(report):
    return {"mode": "recorded_same_candidate_audit_ablation", "model_requests": 0,
            "candidate": copy.deepcopy(report["candidate"]),
            "coordination": "review_unavailable_requires_human_review",
            "original_coordination": report["coordination"]}
