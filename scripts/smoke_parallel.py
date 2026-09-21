"""Separate CLI processes against tasks created by the real P4 comparison."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from anlan.workflows.parallel import canonical_observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--multi-review", action="store_true")
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    bundle = source["results"][0]["bundle"]
    refs = source["results"][1]["bundle"]["collection"]["children"][0]["input"]["parameters"]
    refs_path = args.output.with_suffix(".refs.json")
    refs_path.write_text(json.dumps(refs), encoding="utf-8")
    module = ("anlan.interfaces.multi_review_cli" if args.multi_review
              else "anlan.interfaces.review_cli")
    base = [sys.executable, "-O", "-m", module, "--task", bundle["snapshot"]["task_id"],
            "--refs-file", str(refs_path), "--tenant", bundle["identity"]["tenant_id"],
            "--user", bundle["identity"]["user_id"], "--question", bundle["question"],
            "--as-of", bundle["as_of"], "--facts-dir", str(args.source.with_suffix(".facts")),
            "--trace", str(args.output.with_suffix(".trace.jsonl"))]
    report = {"status": "running", "requests_this_run": 0, "commands": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        try:
            cases = [
                ("serial", ["--collection", "serial"], 0),
                ("parallel", ["--collection", "parallel"], 0),
                ("outsider", ["--collection", "parallel", "--user", "outsider"], 2),
                ("live_blocked", ["--collection", "parallel", "--mode", "deepseek"], 2),
            ]
            if args.multi_review:
                cases = [("multi", [], 0), ("outsider", ["--user", "outsider"], 2)]
            for label, extra, code in cases:
                result = subprocess.run(base + extra, capture_output=True, text=True,
                                        encoding="utf-8", timeout=45,
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                row = {"case": label, "returncode": result.returncode}
                if result.returncode == 0:
                    value = json.loads(result.stdout)
                    row["report"] = value
                    if (not value["material_unchanged"] or value["requests_this_run"] != 0
                            or value["work_package"] != (
                                "P4-WP02" if args.multi_review else "P4-WP01")
                            or value["stop_reason"] != "completed"
                            or canonical_observations(value["observations"])
                            != canonical_observations(bundle["observations"])):
                        raise ValueError("CLI evidence differs")
                    if args.multi_review and (value["audit"] is None or value["model_steps"] != 2):
                        raise ValueError("CLI role path incomplete")
                report["commands"].append(row)
                if result.returncode != code:
                    raise ValueError("Unexpected CLI return code")
            report["status"] = "completed"
        except Exception as exc:
            report.update(status="failed", error_category=type(exc).__name__)
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "commands": len(report["commands"])}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
