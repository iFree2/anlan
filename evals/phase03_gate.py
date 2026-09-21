"""Frozen engineering gate; real PG/BGE/tools with a declared synthesis double."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from evaluate_context import evaluate as evaluate_context
from evaluate_review import ARMS
from evaluate_review import evaluate as evaluate_review

ROOT = Path(__file__).resolve().parents[1]
SCORES = (
    "completed",
    "facts_match",
    "presentation_fields_match",
    "unknowns_complete",
    "selected_knowledge_source_matches",
)


def fingerprint(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        text = json.dumps(
            json.loads(text), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def review_passes(report):
    expected = {
        (case, arm)
        for case in ("rag-001-current", "rag-002-expired", "rag-003-no-knowledge")
        for arm, _, _ in ARMS
    }
    rows = report["results"]
    return (
        report["status"] == "completed"
        and report["mode"] == "scripted"
        and len(rows) == len(expected)
        and {(r["case_id"], r["arm"]) for r in rows} == expected
        and report["requests_this_run"] == 0
        and report["budget_before"] == report["budget_after"]
        and all(
            r["material_unchanged"]
            and all(r["scores"][k] is True for k in SCORES)
            and r["evidence"]["mode"] == "scripted_double"
            and r["evidence"]["requests_this_run"] == 0
            and r["evidence"]["trace_warning"] is None
            and r["evidence"]["stop_reason"] == "completed"
            and 0
            < r["evidence"]["context"]["bytes_used"]
            <= r["evidence"]["context"]["budget_bytes"]
            <= 24000
            for r in rows
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "failed",
        "data_origin": "SYNTHETIC",
        "mode": "engineering_gate",
        "exposure": "developer_seen",
        "created_at": datetime.now(UTC).isoformat(),
        "runner_sha256": fingerprint(Path(__file__)),
        "checks": [],
    }
    with args.output.open("x", encoding="utf-8") as output:
        try:
            manifest = json.loads(
                (ROOT / "evals/phase03-regression-v1/manifest.json").read_text(encoding="utf-8")
            )
            for name, digest in manifest["files"].items():
                if fingerprint(ROOT / name) != digest:
                    raise ValueError("Frozen input mismatch")
            report["manifest"] = manifest
            context = evaluate_context(ROOT / "evals/context-v1/cases.json")
            report["context"] = context
            report["checks"].append(
                {
                    "name": "8_context_cases",
                    "passed": len(context["results"]) == 8 and context["status"] == "passed",
                }
            )
            review_path = args.output.with_name(args.output.stem + ".review.json")
            asyncio.run(
                evaluate_review(SimpleNamespace(mode="scripted", output=review_path)),
                loop_factory=asyncio.SelectorEventLoop,
            )
            review = json.loads(review_path.read_text(encoding="utf-8"))
            report["review_report"] = str(review_path)
            report["checks"].append(
                {"name": "9_same_task_review_arms", "passed": review_passes(review)}
            )
            memory_path = args.output.with_name(args.output.stem + ".memory.json")
            result = subprocess.run(
                [sys.executable, "-O", "scripts/smoke_memory.py", "--output", str(memory_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            memory = json.loads(memory_path.read_text(encoding="utf-8"))
            report["memory_report"] = str(memory_path)
            report["checks"].append(
                {
                    "name": "24_process_memory_lifecycle",
                    "passed": result.returncode == 0
                    and memory["status"] == "passed"
                    and len(memory["commands"]) == 24
                    and len(memory["history"]) == 7
                    and memory["requests_this_run"] == 0
                    and memory["budget_before"] == memory["budget_after"],
                }
            )
            report["status"] = "passed" if all(c["passed"] for c in report["checks"]) else "failed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({k: report[k] for k in ("status", "checks")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
