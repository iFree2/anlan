"""Three seen development examples, explicit offline/live labels, no overwrites."""

import argparse
import asyncio
import hashlib
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx

from anlan.analysis import OfflineAnalyzer
from anlan.contracts import Identity
from anlan.evaluation import score_issues
from anlan.model import DeepSeekAnalyzer, ModelConfig
from anlan.service import WorkflowService
from anlan.trace import JsonlTrace


async def evaluate(args):
    dataset = Path(__file__).parent / "materials-v1" / "dev.jsonl"
    samples = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    report = {
        "created_at": datetime.now(UTC).isoformat(), "mode": args.mode,
        "dataset_version": "materials-v1-dev-seen",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "limitation": "Three seen synthetic dev examples; not holdout or enterprise quality.",
        "results": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation happens before requests; an existing run is never overwritten.
    with args.output.open("x", encoding="utf-8") as output:
        async with AsyncExitStack() as stack:
            if args.mode == "deepseek":
                config = ModelConfig.from_env()
                client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
                analyzer = DeepSeekAnalyzer(config, client)
            else:
                analyzer = OfflineAnalyzer()
            service = WorkflowService(analyzer, JsonlTrace(args.output.with_suffix(".trace.jsonl")))
            identity = Identity(tenant_id="synthetic-eval", user_id="eval-author")
            for sample in samples:
                started = perf_counter()
                state = await service.start(identity, sample["fields"])
                analysis = state["analysis"]
                predicted = [[i["field"], i["kind"]] for i in analysis["issues"]]
                report["results"].append({
                    "case_id": sample["case_id"], "state": state,
                    "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                    "scores": score_issues(predicted, sample["expected"]),
                })
                # Persist each completed attempt, including failure; no hidden success filtering.
                output.seek(0)
                json.dump(report, output, ensure_ascii=False, indent=2)
                output.truncate()
                output.flush()
    print(json.dumps({"mode": args.mode, "cases": len(report["results"]),
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "deepseek"], default="offline")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    try:
        asyncio.run(evaluate(options))
    except FileExistsError:
        parser.exit(2, "结果文件已存在；请选择新的文件名，保留旧结果。\n")
    except ValueError:
        parser.exit(2, "配置无效或缺少 DEEPSEEK_API_KEY；未开始模型请求。\n")
