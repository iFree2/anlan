"""Frozen P4 branches, role coordination and real Java/MCP gate; no model HTTP."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from evaluate_parallel import SCORES
from phase03_gate import fingerprint

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

ROOT = Path(__file__).resolve().parents[1]
CASES = {"rag-001-current", "rag-002-expired", "rag-003-no-knowledge"}


def multi_passes(report):
    rows = report["results"]
    if (
        report["status"] != "completed"
        or report["mode"] != "scripted"
        or report["requests_this_run"] != 0
        or report["budget_before"] != report["budget_after"]
        or len(rows) != 6
        or {(r["case_id"], r["arm"]) for r in rows}
        != {(case, arm) for case in CASES for arm in ("single", "multi")}
    ):
        return False
    for row in rows:
        evidence = row["evidence"]
        if (
            not row["material_unchanged"]
            or not all(row["scores"][s] is True for s in SCORES)
            or evidence["requests_this_run"] != 0
            or evidence["stop_reason"] != "completed"
        ):
            return False
        if row["arm"] == "multi":
            single = next(
                r["evidence"]
                for r in rows
                if r["case_id"] == row["case_id"] and r["arm"] == "single"
            )
            if (
                evidence["model_steps"] != 2
                or len(evidence["children"]) != 2
                or {c["role"] for c in evidence["children"]} != {"risk", "evidence"}
                or any(
                    c["parent_run_id"] != evidence["run_id"]
                    or c["attempt_id"] is not None
                    or c["mode"] != "scripted_double"
                    for c in evidence["children"]
                )
                or evidence["candidate"] != evidence["risk"]["candidate"]
                or evidence["candidate"] != single["candidate"]
                or evidence["risk"]["context"]["sha256"] != single["context"]["sha256"]
                or evidence["audit"] is None
            ):
                return False
    return True


def bridge_passes(report):
    return (
        report["status"] == "completed"
        and report["requests_this_run"] == 0
        and report["budget_before"] == report["budget_after"]
        and report["owned_java_process_stopped"] is True
        and report["mcp_initialization"]["serverInfo"]["name"] == "anlan-read-only-facts"
        and {t["name"] for t in report["tools"]["tools"]}
        == {"query_worker_qualification", "query_area_status"}
        and len(report["cases"]) == 3
        and {r["case_id"] for r in report["cases"]} == CASES
        and all(
            r["same_evidence"]
            and r["material_unchanged"]
            and r["review"]["stop_reason"] == "completed"
            and r["review"]["requests_this_run"] == 0
            and r["review"]["model_steps"] == 2
            for r in report["cases"]
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "failed",
        "mode": "engineering_gate",
        "exposure": "developer_seen",
        "created_at": datetime.now(UTC).isoformat(),
        "runner_sha256": fingerprint(Path(__file__)),
        "optimized_python": bool(sys.flags.optimize),
        "checks": [],
    }

    def snapshot():
        return asyncio.run(
            BudgetLedger(database_url()).snapshot(), loop_factory=asyncio.SelectorEventLoop
        )

    with args.output.open("x", encoding="utf-8") as output:

        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        def run(label, program, extra=()):
            path = args.output.with_name(args.output.stem + "." + label + ".json")
            process = subprocess.run(
                [sys.executable, "-O", program, "--output", str(path), *extra],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=150,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            report[label + "_report"] = str(path)
            save()
            if process.returncode != 0:
                raise ValueError("Subprogram failed; partial report retained")
            return path, json.loads(path.read_text(encoding="utf-8"))

        save()
        try:
            manifest = json.loads(
                (ROOT / "evals/phase04-regression-v1/manifest.json").read_text(encoding="utf-8")
            )
            if any(
                fingerprint(ROOT / path) != digest for path, digest in manifest["files"].items()
            ):
                raise ValueError("Frozen inputs changed")
            report["manifest"] = manifest
            report["budget_before"] = snapshot()
            path, parallel = run("parallel", "evals/evaluate_parallel.py")
            rows = parallel["results"]
            report["checks"].append(
                {
                    "name": "9_serial_parallel_rows",
                    "passed": parallel["status"] == "completed"
                    and parallel["requests_this_run"] == 0
                    and parallel["budget_before"] == parallel["budget_after"]
                    and len(rows) == 9
                    and {(r["case_id"], r["arm"]) for r in rows}
                    == {(case, arm) for case in CASES for arm in ("baseline", "serial", "parallel")}
                    and all(
                        r["same_evidence"]
                        and r["same_context"]
                        and r["same_candidate"]
                        and r["material_unchanged"]
                        for r in rows
                    ),
                }
            )
            _, multi = run("multi", "evals/evaluate_multi_review.py", ["--source", str(path)])
            report["checks"].append({"name": "6_single_multi_rows", "passed": multi_passes(multi)})
            _, bridge = run("bridge", "scripts/smoke_business_bridge.py", ["--source", str(path)])
            report["checks"].append(
                {"name": "3_real_java_mcp_paths", "passed": bridge_passes(bridge)}
            )
            _, cli = run(
                "cli", "scripts/smoke_parallel.py", ["--source", str(path), "--multi-review"]
            )
            report["checks"].append(
                {
                    "name": "2_cross_process_cli",
                    "passed": cli["status"] == "completed"
                    and len(cli["commands"]) == 2
                    and [r["returncode"] for r in cli["commands"]] == [0, 2],
                }
            )
            faults = args.output.with_suffix(".faults.xml")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_parallel.py",
                    "tests/test_multi_review.py",
                    "tests/test_business_bridge.py",
                    "-q",
                    "--junitxml=" + str(faults),
                ],
                capture_output=True,
                timeout=150,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            suite = ET.parse(faults).getroot().find("testsuite")
            report["checks"].append(
                {
                    "name": "61_branch_role_transport_cases",
                    "passed": result.returncode == 0
                    and int(suite.attrib["tests"]) == 61
                    and all(int(suite.attrib[k]) == 0 for k in ("errors", "failures", "skipped")),
                }
            )
            report["budget_after"] = snapshot()
            report["checks"].append(
                {
                    "name": "shared_ledger_unchanged",
                    "passed": report["budget_before"] == report["budget_after"],
                }
            )
            report["status"] = "passed" if all(c["passed"] for c in report["checks"]) else "failed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({"status": report["status"], "checks": report["checks"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
