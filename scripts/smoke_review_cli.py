"""Read a persisted synthetic experiment task from a fresh CLI process."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    bundle = evidence["results"][0]["bundle"]
    refs = args.output.with_suffix(".refs.json")
    refs.write_text(
        json.dumps(
            {"worker_id": "worker-001", "area_id": "area-001", "qualification_type": "welding"}
        ),
        encoding="utf-8",
    )
    report = {"status": "failed", "data_origin": "SYNTHETIC", "commands": []}
    with args.output.open("x", encoding="utf-8") as output:
        try:
            for user, expected in (("other-user", 2), ("safety-manager-demo", 0)):
                command = [
                    sys.executable,
                    "-m",
                    "anlan.review_cli",
                    "--task",
                    bundle["snapshot"]["task_id"],
                    "--tenant",
                    evidence["tenant_id"],
                    "--user",
                    user,
                    "--as-of",
                    evidence["as_of"],
                    "--refs-file",
                    str(refs),
                    "--question",
                    bundle["question"],
                    "--facts-dir",
                    str(args.evidence.with_suffix(".facts")),
                    "--trace",
                    str(args.output.with_suffix(".trace.jsonl")),
                ]
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=45,
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
                report["commands"].append(
                    {
                        "argv": command[2:],
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                if result.returncode != expected:
                    raise RuntimeError("Unexpected CLI result")
                if expected == 0:
                    value = json.loads(result.stdout)
                    if (
                        value["stop_reason"] != "completed"
                        or not value["material_unchanged"]
                        or value["requests_this_run"] != 0
                        or value["candidate"]["presentation"]
                        != {"detail_level": "detailed", "presentation_order": "sources_first"}
                    ):
                        raise RuntimeError("Persisted preference or evidence mismatch")
            report.update(status="passed", requests_this_run=0)
        except Exception as exc:
            report["error_category"] = type(exc).__name__
            raise
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
