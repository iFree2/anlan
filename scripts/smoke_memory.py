"""Real PG, separate CLI processes, explicit checks retained under python -O."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

AS_OF = "2026-09-21T00:00:00Z"


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def budget():
    return asyncio.run(BudgetLedger(database_url()).snapshot(),
                       loop_factory=asyncio.SelectorEventLoop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"data_origin": "SYNTHETIC", "status": "failed", "commands": [],
              "created_at": datetime.now(UTC).isoformat(), "clock_mode": "simulated",
              "as_of": AS_OF, "tenant": "memory-smoke-" + uuid4().hex}
    with args.output.open("x", encoding="utf-8") as output:
        def call(command, *params, expected=0, user="owner", at=AS_OF):
            argv = [sys.executable, "-m", "anlan.interfaces.memory_cli", command,
                    "--tenant", report["tenant"],
                    "--user", user, "--as-of", at, *params]
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                    timeout=45, env={**os.environ, "PYTHONUTF8": "1"})
            report["commands"].append({"command": argv[2:], "exit_code": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr})
            check(result.returncode == expected, "Unexpected CLI exit")
            return json.loads(result.stdout)["result"] if expected == 0 else None

        try:
            report["budget_before"] = budget()
            call("init")
            original = Path("examples/synthetic/memory/feedback-v1.json")
            call("feedback", "--file", str(original))
            m = call("propose", "--source-ref", "synthetic-feedback-detail",
                     "--source-version", "1")
            mid = m["memory_id"]
            def change(op, rev, *extra, **kwargs):
                return call(op, "--memory-id", mid, "--revision", str(rev), *extra, **kwargs)
            check(m["status"] == "candidate" and call("list") == [], "Candidate leaked")
            call("show", "--memory-id", mid, user="other", expected=2)
            change("confirm", 1, user="other", expected=2)
            check(call("show", "--memory-id", mid) == m, "Denied write changed state")
            check(change("reject", 1)["status"] == "rejected", "Reject failed")
            source2 = {**json.loads(original.read_text(encoding="utf-8")), "version": 2,
                       "value": "detailed"}
            correction = args.output.with_suffix(".feedback-v2.json")
            correction.write_text(json.dumps(source2, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            call("feedback", "--file", str(correction))
            call("propose", "--source-ref", source2["source_ref"], "--source-version", "2",
                 expected=2)
            change("correct", 2, "--source-ref", source2["source_ref"], "--source-version", "2")
            active = change("confirm", 3)
            check(call("list") == [active], "Active was not read in fresh process")
            change("reject", 3, expected=2)
            check(call("show", "--memory-id", mid) == active, "Stale write changed state")
            conflicted = change("conflict", 4)
            check(conflicted["status"] == "conflicted" and call("list") == [], "Conflict read")
            change("confirm", 5, expected=2)
            check(change("expire", 5, at="2026-10-21T00:00:00Z")["status"] == "expired",
                  "Expiry boundary failed")
            deleted = change("delete", 6, at="2026-10-21T00:00:00Z")
            check(deleted["status"] == "deleted", "Delete failed")
            check(call("propose", "--source-ref", source2["source_ref"], "--source-version", "2",
                       at="2026-10-21T00:00:00Z") == deleted, "Replay resurrected")
            change("confirm", 7, at="2026-10-21T00:00:00Z", expected=2)
            check(call("list", at="2026-10-21T00:00:00Z") == [], "Deleted read")
            history = call("history", "--memory-id", mid)
            check(len(history) == 7, "Missing audit revisions")
            report["history"] = history
            report["budget_after"] = budget()
            check(report["budget_before"] == report["budget_after"], "Model ledger changed")
            report.update(status="passed", requests_this_run=0)
        except Exception as exc:
            report["error_category"] = type(exc).__name__
            raise
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
