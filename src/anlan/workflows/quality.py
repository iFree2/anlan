"""Offline synthetic evidence inspection and recorded-output replay; no model or DB client."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from anlan.common.models import StrictModel
from anlan.workflows.event_contracts import Identifier, parse_event
from anlan.workflows.perception_contracts import build_context, validate_candidate

MAX_FILE_BYTES = 2 * 1024 * 1024


class Entry(StrictModel):
    id: Identifier
    family: Identifier
    split: Literal["dev", "holdout"]
    kind: Literal["contract", "archive"]
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    index: int = Field(ge=0, le=100, strict=True)


class Manifest(StrictModel):
    schema_version: Literal["quality-manifest-v1"]
    data_origin: Literal["SYNTHETIC"]
    label_origin: str = Field(min_length=1, max_length=200)
    entries: list[Entry] = Field(min_length=1, max_length=100)


def read_bounded(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Quality input exceeds the offline file bound")
    return raw


def load_corpus(manifest_path, root):
    """Verify explicit sources and keep same-source/family/event records in one split."""
    manifest = Manifest.model_validate_json(read_bounded(manifest_path))
    root = Path(root).resolve()
    seen_ids, partitions, records = set(), {}, []
    for entry in manifest.entries:
        source = (root / entry.path).resolve()
        if not source.is_relative_to(root) or Path(entry.path).is_absolute():
            raise ValueError("Quality source escapes the selected repository")
        raw = read_bounded(source)
        if hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise ValueError("Quality source fingerprint differs from frozen manifest")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("data_origin") != "SYNTHETIC":
            raise ValueError("Only explicitly synthetic evidence is accepted")
        if entry.id in seen_ids:
            raise ValueError("Duplicate quality case identity")
        seen_ids.add(entry.id)
        if entry.kind == "contract":
            case = data["cases"][entry.index]
            if (case["data_origin"] != "SYNTHETIC" or case["id"] != entry.id
                    or case["family"] != entry.family):
                raise ValueError("Contract case provenance differs")
            context = build_context(case["event"], case["bundle"])
            candidate, expected = case["candidate"], case["expected"]
            feedback, original_stop = case["feedback"], None
            event = case["event"]
            run_id = case["bundle"]["snapshot"]["run_id"]
            feedback_origin = feedback["origin"] if feedback else None
            feedback_decision = feedback["decision"] if feedback else None
        else:
            row = data["rows"][entry.index]
            report = row["review"]["result"]["report"]
            event, context = report["event"], report["context"]
            original_stop = report["stop_reason"]
            candidate = report["candidate"] or report["rejected_candidate"]
            expected = ("not_replayable" if candidate is None else
                        "accepted" if original_stop == "completed" else "rejected")
            feedback = row.get("feedback")
            if feedback and feedback["review_id"] != row["review"]["review_id"]:
                raise ValueError("Feedback belongs to another review")
            feedback_origin = row.get("feedback_origin") if feedback else None
            feedback_decision = feedback["feedback"]["decision"] if feedback else None
            run_id = row["review"]["run_id"]
        parse_event(event)
        if context:
            context_data = json.loads(context["messages"][1]["content"])
            if context_data.get("data_origin") != "SYNTHETIC" or context_data["event"] != event:
                raise ValueError("Recorded context does not match the synthetic event")
        if expected not in {"accepted", "rejected", "not_replayable"}:
            raise ValueError("Unsupported expected outcome")
        if feedback_origin not in {None, "synthetic_replay_actor", "synthetic_dataset_annotation"}:
            raise ValueError("Unsupported feedback provenance")
        if feedback_decision not in {
            None, "confirmed_event", "disputed_event", "needs_verification"
        }:
            raise ValueError("Unsupported feedback decision")
        for key in (("family", entry.family), ("source", entry.sha256),
                    ("event", event["event_id"])):
            if key in partitions and partitions[key] != entry.split:
                raise ValueError("Related evidence cannot cross development and holdout splits")
            partitions[key] = entry.split
        unknowns = (candidate.get("unknown_observation_ids", [])
                    if isinstance(candidate, dict) else [])
        duplicate_unknown = (
            isinstance(unknowns, list) and all(isinstance(x, str) for x in unknowns)
            and len(unknowns) != len(set(unknowns))
        )
        records.append({"id": entry.id, "family": entry.family, "split": entry.split,
                        "source_sha256": entry.sha256, "run_id": run_id,
                        "feedback_origin": feedback_origin, "feedback_decision": feedback_decision,
                        "original_stop": original_stop, "expected": expected,
                        "root_cause": "duplicate_unknown_present" if duplicate_unknown
                        else "not_established",
                        "_candidate": candidate, "_context": context})
    return records


def inspect_records(records):
    """Metadata only; pending synthetic feedback alone is not proof of a bad output."""
    return [{key: value for key, value in record.items() if not key.startswith("_")}
            for record in records]


def replay_records(records, *, split):
    if split not in {"dev", "holdout"}:
        raise ValueError("Choose an explicit split")
    result = []
    for record in records:
        if record["split"] != split:
            continue
        candidate, context = record["_candidate"], record["_context"]
        if candidate is None or context is None:
            actual = "not_replayable"
        else:
            try:
                validate_candidate(candidate, context)
            except ValueError:
                actual = "rejected"
            else:
                actual = "accepted"
        result.append(inspect_records([record])[0] | {
            "actual": actual, "matches_expected": actual == record["expected"],
            "mode": "recorded_output_replay", "model_requests": 0,
        })
    return result
