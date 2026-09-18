"""Cross-process synthetic demo; saves commands and snapshots, never connection credentials."""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("ANLAN_DATABASE_URL"):
        parser.error("Run dev-postgres.ps1 -Action Env first; credentials stay in the environment.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"created_at": datetime.now(UTC).isoformat(), "mode": "offline",
              "data_origin": "SYNTHETIC", "commands": []}
    with args.output.open("x", encoding="utf-8") as output:
        def call(*command, expected=0):
            argv = [sys.executable, "-m", "anlan", *command,
                    "--trace", str(args.output.with_suffix(".trace.jsonl"))]
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                    timeout=30, env={**os.environ, "PYTHONUTF8": "1"})
            report["commands"].append({"argv": argv, "exit_code": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode != expected:
                raise AssertionError(f"CLI step {command[0]} failed: {result.returncode}")
            return json.loads(result.stdout) if expected == 0 else None

        try:
            first = call("start")
            task = first["task_id"]
            report["task_id"] = task
            assert call("show", "--task", task)["fields"] == first["fields"]
            location = ("resume", "--task", task, "--revision", "1", "--request-id", "location-1",
                        "--fields-file", "examples/synthetic/location.json")
            second = call(*location)
            assert second["revision"] == 2
            assert call(*location) == second
            call("resume", "--task", task, "--revision", "1", "--request-id", "stale",
                 "--fields-file", "examples/synthetic/method.json", expected=2)
            call("show", "--task", task, "--tenant", "other-synthetic", expected=2)
            final = call("resume", "--task", task, "--revision", "2", "--request-id", "method-1",
                         "--fields-file", "examples/synthetic/method.json")
            assert final["revision"] == 3 and final["status"] == "awaiting_review"
            assert call("recover", "--task", task) == final
            history = call("history", "--task", task)
            assert len(history["operations"]) == 3
            with psycopg.connect(os.environ["ANLAN_DATABASE_URL"], row_factory=dict_row) as conn:
                report["postgres_version"] = conn.execute("SELECT version()").fetchone()["version"]
                report["sql_runs"] = conn.execute(
                    "SELECT request_id,run_id,kind,expected_revision, "
                    "result->>'revision' AS result_revision, result->>'status' AS result_status "
                    "FROM anlan_v2.anlan_operations WHERE task_id=%s ORDER BY started_at", (task,),
                ).fetchall()
            assert len(report["sql_runs"]) == 3
            report["status"] = "passed"
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "task_id": report["task_id"],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
