"""User-scoped synthetic review, fixed read-only collection and one synthesis request."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

from anlan.analysis import OfflineAnalyzer
from anlan.contracts import Identity
from anlan.embeddings import LocalEmbeddings
from anlan.knowledge import KnowledgeStore
from anlan.knowledge_tool import UnavailableKnowledgeStore
from anlan.live import production_ledger
from anlan.memory import MemoryStore
from anlan.model import ModelConfig
from anlan.parallel import WORK_PACKAGE as COLLECTION_PACKAGE
from anlan.parallel import collect_parallel
from anlan.postgres import database_url, postgres_service
from anlan.registry import AccessDenied, InvalidTransition
from anlan.review import DeepSeekReviewModel, ScriptedReviewModel, collect_review, synthesize
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace


async def run(args):
    collection = getattr(args, "collection", "baseline")
    if collection != "baseline" and args.mode == "deepseek":
        raise ValueError("P4-WP01 has no live model entry")
    identity = Identity(tenant_id=args.tenant, user_id=args.user)
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone required")
    clock = lambda: now  # noqa: E731
    async with postgres_service(database_url(), OfflineAnalyzer()) as service:
        await service.get(identity, args.task)
        try:
            knowledge = KnowledgeStore(database_url(), await LocalEmbeddings.create(), clock=clock)
        except Exception:
            knowledge = UnavailableKnowledgeStore(clock)
        collector = collect_review if collection == "baseline" else collect_parallel
        options = {} if collection == "baseline" else {"parallel": collection == "parallel"}
        bundle = await collector(service, identity, args.task,
            json.loads(args.refs_file.read_text(encoding="utf-8-sig")), args.question,
            FactTools(args.facts_dir, clock=clock), knowledge,
            MemoryStore(database_url(), clock=clock), trace=JsonlTrace(args.trace), **options)
        if args.mode == "deepseek":
            ledger = await production_ledger()
            before = await ledger.snapshot()
            async with httpx.AsyncClient(follow_redirects=False) as client:
                model = DeepSeekReviewModel(ModelConfig.from_env(), client, ledger)
                result = await synthesize(bundle, model, use_memory=not args.no_memory,
                    use_knowledge=not args.no_knowledge, budget_bytes=args.budget_bytes,
                    trace=JsonlTrace(args.trace))
            result["budget_before"] = before
            result["budget_after"] = await ledger.snapshot()
        else:
            result = await synthesize(bundle, ScriptedReviewModel(), use_memory=not args.no_memory,
                use_knowledge=not args.no_knowledge, budget_bytes=args.budget_bytes,
                trace=JsonlTrace(args.trace))
        result["material_unchanged"] = await service.get(identity, args.task) == bundle["snapshot"]
        if not result["material_unchanged"]:
            result["candidate_status"] = "stale_material_revision"
        result["clock_mode"] = "simulated" if args.as_of else "system_utc"
        if collection != "baseline":
            result["collection"] = bundle["collection"]
            result["work_package"] = COLLECTION_PACKAGE
            result["notice"] = "确定性职责分支＋综合替身；不是多个自治模型或作业批准。"
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--refs-file", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--tenant", default="synthetic-demo")
    parser.add_argument("--user", default="safety-manager-demo")
    parser.add_argument("--facts-dir", type=Path, default=Path("examples/synthetic/facts-v1"))
    parser.add_argument("--as-of")
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    parser.add_argument("--collection", choices=["baseline", "serial", "parallel"],
                        default="baseline")
    parser.add_argument("--budget-bytes", type=int, default=24000)
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--no-knowledge", action="store_true")
    parser.add_argument("--trace", type=Path, default=Path(".runtime/review.trace.jsonl"))
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
    except (ValueError, OSError, psycopg.Error, AccessDenied, InvalidTransition):
        parser.exit(2, "综合请求无法执行；请检查任务归属、输入、时间和本地配置，连接详情已隐藏。\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
