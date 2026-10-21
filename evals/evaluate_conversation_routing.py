"""Score saved conversation proposals without making provider requests."""

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = {
    "case_id",
    "split",
    "slice",
    "expected_intent",
    "predicted_intent",
    "expected_fields",
    "predicted_fields",
    "confirmation_required",
    "confirmation_requested",
    "confirmation_granted",
    "business_writes",
    "max_business_writes",
}
SPLIT_REPORT_NAMES = {
    "development": "development_seen",
    "holdout": "seen_post_fix_regression",
}


def _rate(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def _validate(rows):
    if not rows:
        raise ValueError("results must contain at least one outcome")
    seen = set()
    for index, row in enumerate(rows):
        missing = sorted(REQUIRED - set(row))
        if missing:
            raise ValueError(f"row {index} missing {', '.join(missing)}")
        case_id = row["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"row {index} has invalid case_id")
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        if not isinstance(row["slice"], str) or not row["slice"]:
            raise ValueError(f"row {index} has invalid slice")
        if row["split"] not in {"development", "holdout"}:
            raise ValueError(f"row {index} has invalid split")
        for name in ("business_writes", "max_business_writes"):
            if not isinstance(row[name], int) or isinstance(row[name], bool) or row[name] < 0:
                raise ValueError(f"row {index} has invalid {name}")
        for name in (
            "confirmation_required",
            "confirmation_requested",
            "confirmation_granted",
        ):
            if not isinstance(row[name], bool):
                raise ValueError(f"row {index} has invalid {name}")
        if not isinstance(row["expected_fields"], dict) or not isinstance(
            row["predicted_fields"], dict
        ):
            raise ValueError(f"row {index} has invalid fields")


def _bucket(rows):
    return {
        "cases": len(rows),
        "correct": sum(row["expected_intent"] == row["predicted_intent"] for row in rows),
    }


def score(outcomes):
    """Return deterministic routing, confirmation, extraction, and safety metrics."""
    rows = sorted((dict(row) for row in outcomes), key=lambda row: row["case_id"])
    _validate(rows)
    confusion = Counter(
        (row["expected_intent"], row["predicted_intent"]) for row in rows
    )
    hot = [row for row in rows if row["expected_intent"] == "hot_work_candidate"]
    chat = [row for row in rows if row["expected_intent"] == "casual_chat"]
    confirmation = [row for row in rows if row["confirmation_required"]]
    field_rows = [row for row in rows if row["expected_fields"]]
    groups = defaultdict(list)
    splits = defaultdict(list)
    for row in rows:
        groups[row["slice"]].append(row)
        splits[row["split"]].append(row)
    correct = sum(row["expected_intent"] == row["predicted_intent"] for row in rows)
    exact = sum(row["expected_fields"] == row["predicted_fields"] for row in field_rows)
    unconfirmed_writes = sum(
        max(0, row["business_writes"] - row["max_business_writes"])
        for row in rows
        if not row["confirmation_granted"]
    )
    return {
        "schema_version": "conversation-routing-report-v1",
        "result_kind": "saved_proposal_evaluation",
        "routing": {
            "cases": len(rows),
            "correct": correct,
            "accuracy": _rate(correct, len(rows)),
            "hot_work_expected": len(hot),
            "hot_work_detected": sum(
                row["predicted_intent"] == "hot_work_candidate" for row in hot
            ),
            "hot_work_recall": _rate(
                sum(row["predicted_intent"] == "hot_work_candidate" for row in hot),
                len(hot),
            ),
            "chat_false_positive": sum(
                row["predicted_intent"] == "hot_work_candidate" for row in chat
            ),
            "confusion": {
                f"{expected}->{predicted}": count
                for (expected, predicted), count in sorted(confusion.items())
            },
        },
        "confirmation": {
            "required": len(confirmation),
            "requested": sum(row["confirmation_requested"] for row in confirmation),
            "coverage": _rate(
                sum(row["confirmation_requested"] for row in confirmation),
                len(confirmation),
            ),
        },
        "fields": {
            "eligible": len(field_rows),
            "exact": exact,
            "exact_match_rate": _rate(exact, len(field_rows)),
        },
        "safety": {"unconfirmed_business_writes": unconfirmed_writes},
        "splits": {
            SPLIT_REPORT_NAMES[name]: _bucket(splits[name]) for name in sorted(splits)
        },
        "slices": {name: _bucket(groups[name]) for name in sorted(groups)},
    }


def write_report(path, report):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def generate_scripted_results(cases):
    """Run the deterministic protocol double; this is not provider-quality evidence."""
    from anlan.conversation.contracts import PendingIntent
    from anlan.llm.conversation import (
        ConversationContext,
        ScriptedConversationModel,
        VisibleMessage,
    )

    outcomes = []
    model = ScriptedConversationModel()
    for case in sorted(cases, key=lambda item: item["case_id"]):
        state = case["conversation_state"]
        pending_data = state.get("pending_intent")
        pending = None
        if pending_data:
            pending = PendingIntent(
                intent_id=f"intent-{case['case_id']}",
                kind=pending_data["kind"],
                fields=pending_data.get("fields", {}),
                revision=1,
            )
        history = [VisibleMessage.model_validate(item) for item in case["visible_history"]]
        history.append(VisibleMessage(role="user", text=case["input"]))
        proposal = await model.classify(
            ConversationContext(
                status=state["status"],
                messages=history,
                pending_intent=pending,
                task_projection=(
                    {"task_id": state["active_task_id"], "status": "waiting_input"}
                    if state.get("active_task_id")
                    else None
                ),
            ),
            run_id=f"freeze:{case['case_id']}",
        )
        outcomes.append(
            {
                "case_id": case["case_id"],
                "split": case["split"],
                "slice": case["slice"],
                "expected_intent": case["expected_intent"],
                "predicted_intent": proposal.intent,
                "expected_fields": case["expected_fields"],
                "predicted_fields": proposal.fields,
                "confirmation_required": case["confirmation_required"],
                "confirmation_requested": proposal.requires_confirmation,
                "confirmation_granted": False,
                "business_writes": 0,
                "max_business_writes": case["max_business_writes"],
            }
        )
    return {
        "schema_version": "conversation-routing-results-v1",
        "result_kind": "scripted_double",
        "classifier_version": "scripted-intent-v1",
        "live_provider_requests": 0,
        "outcomes": outcomes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--generate-scripted-from", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if args.generate_scripted_from:
        cases = json.loads(args.generate_scripted_from.read_text(encoding="utf-8"))
        payload = asyncio.run(
            generate_scripted_results(cases["cases"]),
            loop_factory=asyncio.SelectorEventLoop,
        )
        write_report(args.output, payload)
        return
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("result_kind") not in {"scripted_double", "live_provider"}:
        raise ValueError("input must explicitly label result_kind")
    report = score(payload.get("outcomes"))
    report["input_result_kind"] = payload["result_kind"]
    report["classifier_version"] = payload.get("classifier_version")
    report["live_provider_requests"] = payload.get("live_provider_requests")
    write_report(args.output, report)


if __name__ == "__main__":
    main()
