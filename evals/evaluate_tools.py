"""三个已见合成工具任务，协议替身/真实请求分开，保留失败且不覆盖结果。"""

import argparse
import asyncio
import hashlib
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx

from anlan.common.models import Identity
from anlan.infrastructure.live import production_ledger
from anlan.infrastructure.trace import JsonlTrace
from anlan.llm.config import ModelConfig
from anlan.llm.tool_model import PROMPT_VERSION, SYSTEM_PROMPT, DeepSeekToolModel, ScriptedToolModel
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService
from anlan.workflows.tool_loop import check_facts_agent


def score(report, case):
    executed = [r for r in report["results"] if r["executed"]]
    actual = {r["tool"]: [r["outcome"], r["reason"]] for r in executed}
    return {
        "required_tools_observed": set(actual) == set(case["expected"]),
        "observation_outcomes_match": actual == case["expected"],
        "all_actions_valid": all(r["executed"] for r in report["results"]),
        "stopped_normally": report["stop_reason"] == "completed",
        "summary_semantic_support": "not_evaluated",
    }


async def evaluate(args):
    config = ModelConfig.from_env() if args.mode == "deepseek" else None
    raw = (Path(__file__).parent / "tools-v1/cases.json").read_bytes()
    dataset = json.loads(raw)
    report = {
        "created_at": datetime.now(UTC).isoformat(), "mode": args.mode,
        "dataset_version": dataset["version"], "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "data_origin": "SYNTHETIC", "exposure": "developer_seen", "clock_mode": "simulated",
        "as_of": dataset["as_of"], "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "model": config.model if config else None, "automatic_retries": 0,
        "limits": {"requests_per_task": 3, "tasks": 3, "max_tokens": 1024,
                   "timeout_seconds": 20, "package_requests": 10, "project_requests": 100},
        "limitation": "Three seen synthetic dev tasks; summary meaning is not graded.",
        "results": [], "status": "running",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        save()
        try:
            async with AsyncExitStack() as stack:
                ledger = await production_ledger() if config else None
                if ledger:
                    report["budget_before"] = await ledger.snapshot()
                client = await stack.enter_async_context(
                    httpx.AsyncClient(follow_redirects=False)) if config else None
                identity = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
                for case in dataset["cases"]:
                    model = DeepSeekToolModel(config, client, ledger) \
                        if config else ScriptedToolModel()
                    service = WorkflowService(OfflineAnalyzer())
                    state = await service.start(identity, {
                        "work_location_description": "SYNTHETIC：A区1号台",
                        "work_object_description": "SYNTHETIC：试件接缝",
                        "work_method_description": "SYNTHETIC：电弧焊",
                        "attachment_description": case.get(
                            "untrusted_material", "SYNTHETIC：位置图"),
                    })
                    evidence = await check_facts_agent(
                        service, identity, state["task_id"], case["references"],
                        FactTools(Path("examples/synthetic/facts-v1"),
                                  clock=lambda: datetime.fromisoformat(dataset["as_of"])), model,
                        JsonlTrace(args.output.with_suffix(".trace.jsonl")))
                    report["results"].append({"case_id": case["id"], "evidence": evidence,
                                              "scores": score(evidence, case),
                                              "material_unchanged": await service.get(
                                                  identity, state["task_id"]) == state})
                    if ledger:
                        report["budget_after"] = await ledger.snapshot()
                    save()
                run_ids = {row["evidence"]["run_id"] for row in report["results"]}
                reservations = [a for a in report.get("budget_after", {}).get("attempts", [])
                                if a["run_id"] in run_ids]
                known_tokens = [a["usage"]["total_tokens"] for a in reservations
                                if a["usage"] and type(a["usage"].get("total_tokens")) is int]
                report["summary"] = {
                    "cases": len(report["results"]),
                    "requests_this_run": len(reservations),
                    "known_total_tokens": sum(known_tokens) if known_tokens
                        else (None if reservations else 0),
                    "usage_complete": all(a["usage"] and all(
                        type(a["usage"].get(k)) is int for k in (
                            "prompt_tokens", "completion_tokens", "total_tokens"))
                        for a in reservations),
                    **{key: sum(row["scores"][key] for row in report["results"]) for key in (
                        "required_tools_observed", "observation_outcomes_match",
                        "all_actions_valid", "stopped_normally")},
                }
                report["status"] = "completed"
        except Exception as exc:
            report["status"] = "failed"
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({"status": report["status"], "mode": args.mode,
                      "summary": report.get("summary"), "output": str(args.output)}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(evaluate(options), loop_factory=asyncio.SelectorEventLoop))
    except (ValueError, FileExistsError):
        parser.exit(2, "配置无效或结果已存在；请检查环境，使用新输出路径，不输出凭据。\n")
