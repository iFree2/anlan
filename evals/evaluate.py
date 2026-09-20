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
from anlan.budget import BudgetError
from anlan.contracts import Identity
from anlan.evaluation import score_issues
from anlan.live import production_ledger
from anlan.model import PROMPT_VERSION, SYSTEM_PROMPT, DeepSeekAnalyzer, ModelConfig
from anlan.service import WorkflowService
from anlan.trace import JsonlTrace


def summarize(results: list[dict], request_attempts: int) -> dict:
    tp, fp, fn = (sum(row["scores"][key] for row in results) for key in ("tp", "fp", "fn"))
    usage = [row["state"]["analysis"].get("usage") or {} for row in results]
    token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    totals = {}
    for key in token_keys:
        known = [item[key] for item in usage if type(item.get(key)) is int]
        totals[f"known_{key}"] = sum(known) if known else (0 if request_attempts == 0 else None)
    return {
        "cases": len(results), "request_attempts": request_attempts,
        "exact_matches": sum(row["scores"]["exact_match"] for row in results),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "semantic_failures": sum(row["state"]["analysis"]["semantic_status"] == "failed"
                                 for row in results),
        "usage_complete": request_attempts == 0 or (
            len(usage) == request_attempts
            and all(all(type(item.get(key)) is int for key in token_keys) for item in usage)
        ),
        **totals,
    }


async def evaluate(args):
    config = ModelConfig.from_env() if args.mode == "deepseek" else None
    ledger = await production_ledger() if config else None
    dataset = Path(__file__).parent / "materials-v1" / "dev.jsonl"
    samples = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    report = {
        "created_at": datetime.now(UTC).isoformat(), "mode": args.mode,
        "dataset_version": "materials-v1-dev-seen",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "limitation": "Three seen synthetic dev examples; not holdout or enterprise quality.",
        "configuration": {
            "requested_model": config.model if config else None,
            "prompt_version": PROMPT_VERSION if config else None,
            "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() if config else None,
            "max_requests": config.max_requests if config else 0,
            "timeout_seconds": config.timeout_seconds if config else None,
            "max_output_tokens": 1024 if config else None,
            "temperature": 0 if config else None,
            "automatic_retries": 0,
        },
        "results": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation happens before requests; an existing run is never overwritten.
    with args.output.open("x", encoding="utf-8") as output:
        async with AsyncExitStack() as stack:
            if args.mode == "deepseek":
                client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
                analyzer = DeepSeekAnalyzer(config, client, ledger=ledger)
            else:
                analyzer = OfflineAnalyzer()
            service = WorkflowService(analyzer, JsonlTrace(args.output.with_suffix(".trace.jsonl")),
                                      mode=args.mode)
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
                report["summary"] = summarize(
                    report["results"], getattr(analyzer, "requests_used", 0))
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
        asyncio.run(evaluate(options), loop_factory=asyncio.SelectorEventLoop)
    except FileExistsError:
        parser.exit(2, "结果文件已存在；请选择新的文件名，保留旧结果。\n")
    except ValueError:
        parser.exit(2, "配置无效或缺少 DEEPSEEK_API_KEY；未开始模型请求。\n")
    except BudgetError as exc:
        parser.exit(2, f"{exc}\n")
