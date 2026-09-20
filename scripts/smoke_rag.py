"""使用已准备的合成实验租户，验证三工具CLI跨进程与材料不变。"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source_report.read_text(encoding="utf-8-sig"))
    if source.get("data_origin") != "SYNTHETIC" or source.get("status") != "completed":
        parser.error("需要已完成的合成RAG实验记录。")
    report = {"status": "failed", "data_origin": "SYNTHETIC", "mode": "scripted_double",
              "requests_this_run": 0, "commands": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        def call(*command, expected=0):
            argv = [sys.executable, "-m", "anlan", *command, "--tenant", source["tenant_id"],
                    "--trace", str(args.output.with_suffix(".trace.jsonl"))]
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                    timeout=60, env={**os.environ, "PYTHONUTF8": "1"})
            report["commands"].append({"argv": argv, "exit_code": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode != expected:
                raise AssertionError("RAG CLI failed")
            return json.loads(result.stdout) if expected == 0 else None

        try:
            before = call("start")
            task = before["task_id"]
            result = call("check-facts-agent", "--task", task,
                          "--refs-file", "examples/synthetic/fact-refs.json",
                          "--facts-dir", str(args.source_report.with_suffix(".facts")),
                          "--knowledge-question", "动火现场需要怎样安排监护人员？",
                          "--as-of", "2026-09-20T12:00:00Z")
            assert result["stop_reason"] == "completed" and result["tool_calls"] == 3
            assert result["summary"]["knowledge_citations"]
            assert call("show", "--task", task) == before
            assert len(call("history", "--task", task)["operations"]) == 1
            report["status"] = "passed"
            report["material_unchanged"] = True
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "commands": len(report["commands"]),
                      "output": str(args.output)}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
