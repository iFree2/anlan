"""P2-WP01只读事实演示：真实CLI/PG/JSON查询，显式标注延迟注入。"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from anlan.analysis import OfflineAnalyzer
from anlan.contracts import Identity
from anlan.facts import check_facts
from anlan.postgres import database_url, postgres_service
from anlan.tools.queries import FactTools, read_bytes
from anlan.trace import JsonlTrace

AS_OF = "2026-09-20T12:00:00+00:00"


async def injected_scenarios(task_id, trace_path):
    identity = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
    refs = json.loads(Path("examples/synthetic/fact-refs.json").read_text(encoding="utf-8"))

    async def slow_qualification(path):
        if path.name == "qualifications.json":
            await asyncio.sleep(10)
        return await read_bytes(path)

    scenarios = []
    async with postgres_service(database_url(), OfflineAnalyzer()) as service:
        before = await service.get(identity, task_id)
        for label, query_refs, reader, expected in [
            ("qualification_timeout_injected", refs, slow_qualification, ["timeout", None]),
            ("foreign_object_rejected", {**refs, "worker_id": "other-tenant-worker"},
             read_bytes, ["access_denied", None]),
            ("missing_and_expired", {**refs, "worker_id": "worker-missing",
                                     "area_id": "area-expired"},
             read_bytes, ["missing", "expired"]),
        ]:
            tools = FactTools(Path("examples/synthetic/facts-v1"),
                              clock=lambda: datetime.fromisoformat(AS_OF),
                              reader=reader, timeout_seconds=0.2)
            report = await check_facts(service, identity, task_id, query_refs, tools,
                                       JsonlTrace(trace_path))
            unchanged = await service.get(identity, task_id) == before
            passed = [r["reason"] for r in report["results"]] == expected and unchanged
            scenarios.append({"name": label, "injected_delay": reader is slow_qualification,
                              "clock_mode": "simulated", "evidence": report,
                              "task_unchanged": unchanged, "passed": passed})
    return scenarios


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("ANLAN_DATABASE_URL"):
        parser.error("先加载项目PG环境；不输出数据库凭据。")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    trace_path = args.output.with_suffix(".trace.jsonl")
    report = {"created_at": datetime.now(UTC).isoformat(), "data_origin": "SYNTHETIC",
              "requests_this_run": 0, "tokens_this_run": 0, "status": "failed",
              "clock_mode": "simulated", "as_of": AS_OF, "commands": [], "scenarios": []}
    with args.output.open("x", encoding="utf-8") as output:
        def call(*command, expected=0):
            argv = [sys.executable, "-m", "anlan", *command, "--trace", str(trace_path)]
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                    timeout=30, env={**os.environ, "PYTHONUTF8": "1"})
            report["commands"].append({"argv": argv, "exit_code": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr,
                                       "passed": result.returncode == expected})
            if result.returncode != expected:
                raise AssertionError("CLI exit code differs from expected")
            return json.loads(result.stdout) if expected == 0 else None

        try:
            before = call("start")
            task_id = before["task_id"]
            report["task_id"] = task_id
            normal = call("check-facts", "--task", task_id, "--refs-file",
                          "examples/synthetic/fact-refs.json", "--as-of", AS_OF)
            assert [r["outcome"] for r in normal["results"]] == ["ok", "ok"]
            call("check-facts", "--task", task_id, "--tenant", "other-tenant",
                 "--refs-file", "examples/synthetic/fact-refs.json", expected=2)
            report["scenarios"] = asyncio.run(
                injected_scenarios(task_id, trace_path), loop_factory=asyncio.SelectorEventLoop)
            assert all(s["passed"] for s in report["scenarios"])
            assert call("show", "--task", task_id) == before
            assert len(call("history", "--task", task_id)["operations"]) == 1
            report["task_unchanged"] = True
            report["status"] = "passed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "commands": len(report["commands"]),
                      "scenarios": len(report["scenarios"]), "output": str(args.output)}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
