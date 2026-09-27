"""P5 engineering evidence gate; explicitly does not pass real perception-model quality."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from evaluate_perception import chain_passes

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

ROOT = Path(__file__).resolve().parents[1]


def current_sources():
    spec = importlib.util.spec_from_file_location("ci_fingerprints", ROOT / "scripts/ci.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.source_fingerprints(ROOT)


def source_set_matches(ci, current):
    return bool(ci.get("sources_after")) and ci["sources_after"] == current


def package_matches(ci, service):
    expected = {p: h for p, h in ci.get("sources_after", {}).items() if p.startswith("src/anlan/")}
    return bool(expected) and expected == service.get("interpreter", {}).get("package_files")


def service_passes(report):
    rows = report.get("rows", [])
    return (
        report.get("status") == "passed"
        and "error_category" not in report
        and report.get("requests_this_run") == 0
        and report.get("restarts") == 1
        and report.get("owned_process_stopped") is True
        and report.get("budget_before") == report.get("budget_after")
        and "site-packages" in report.get("interpreter", {}).get("package", "")
        and len(rows) == 2
        and {r["kind"] for r in rows} == {"helmet_missing", "gas_abnormal"}
        and all(
            r["raw_unchanged"]
            and r["restart_snapshot_equal"]
            and r["review"]["result"]["status"] == "completed"
            and r["review"]["result"]["report"]["mode"] == "scripted_double"
            and r["review"]["result"]["report"]["requests_this_run"] == 0
            and r["feedback"]["revision"] == 2
            for r in rows
        )
    )


def ci_passes(report):
    summary = report.get("test_summary", {})
    return (
        report.get("status") == "passed"
        and summary.get("tests", 0) >= 395
        and all(summary.get(k) == 0 for k in ("errors", "failures", "skipped"))
        and {c["name"] for c in report.get("checks", [])} == {"lock", "lint", "tests"}
        and all(c["returncode"] == 0 for c in report["checks"])
        and bool(report.get("sources_before"))
        and report["sources_before"] == report.get("sources_after")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ci", type=Path, required=True)
    parser.add_argument("--service", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new report path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "failed",
        "mode": "engineering_gate",
        "checks": [],
        "requests_this_run": 0,
        "model_quality_status": "not_passed",
        "open_quality_items": ["Q-P5-001"],
        "compose": "not_run",
        "remote_ci": "not_run",
    }

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(name, condition):
        report["checks"].append({"name": name, "passed": bool(condition)})
        save()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def run(label, script):
        path = args.output.with_suffix("." + label + ".json")
        process = subprocess.run(
            [sys.executable, "-O", script, "--output", str(path)],
            capture_output=True,
            timeout=300,
            env=os.environ | {"PYTHONIOENCODING": "utf-8"},
        )
        report[label + "_report"] = str(path)
        save()
        if process.returncode:
            raise ValueError("Child replay failed; its report retained")
        return read(path)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        ledger = BudgetLedger(database_url())
        try:
            report["budget_before"] = runner.run(ledger.snapshot())
            manifest = read(ROOT / "evals/phase05-regression-v1/manifest.json")
            check(
                "frozen_inputs",
                all(
                    hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
                    for p, h in manifest["files"].items()
                ),
            )
            ci = read(args.ci)
            check("full_local_ci_zero_skips", ci_passes(ci))
            check(
                "ci_sources_still_match",
                source_set_matches(ci, current_sources()),
            )
            service = read(args.service)
            check("clean_wheel_http_sse_restart", service_passes(service))
            check("installed_wheel_matches_tested_source", package_matches(ci, service))
            perception = run("perception", "evals/evaluate_perception.py")
            check(
                "two_event_feedback_revision_chains",
                perception["status"] == "completed"
                and perception["requests_this_run"] == 0
                and len(perception["rows"]) == 2
                and all(chain_passes(r) for r in perception["rows"])
                and perception["budget_before"] == perception["budget_after"],
            )
            p4 = run("p4", "evals/phase04_gate.py")
            check("previous_phase_gate", p4["status"] == "passed")
            report["budget_after"] = runner.run(ledger.snapshot())
            check("shared_ledger_unchanged", report["budget_before"] == report["budget_after"])
            report["status"] = "passed" if all(c["passed"] for c in report["checks"]) else "failed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({k: report[k] for k in ("status", "checks", "model_quality_status")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
