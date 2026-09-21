"""Synthetic bounded risk/evidence roles; identity gate before dependencies and credentials."""

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
from anlan.multi_review import (
    WORK_PACKAGE,
    DeepSeekEvidenceModel,
    ScriptedEvidenceModel,
    multi_review,
)
from anlan.parallel import collect_parallel
from anlan.postgres import database_url, postgres_service
from anlan.registry import AccessDenied, InvalidTransition
from anlan.review import DeepSeekReviewModel, ScriptedReviewModel
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace


async def run(args):
    identity = Identity(tenant_id=args.tenant, user_id=args.user)
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone required")
    clock = lambda: now  # noqa: E731
    trace = JsonlTrace(args.trace)
    async with postgres_service(database_url(), OfflineAnalyzer()) as service:
        await service.get(identity, args.task)
        try:
            knowledge = KnowledgeStore(database_url(), await LocalEmbeddings.create(), clock=clock)
        except Exception:
            knowledge = UnavailableKnowledgeStore(clock)
        bundle = await collect_parallel(service, identity, args.task,
            json.loads(args.refs_file.read_text(encoding="utf-8-sig")), args.question,
            FactTools(args.facts_dir, clock=clock), knowledge,
            MemoryStore(database_url(), clock=clock), trace=trace)
        if args.mode == "deepseek":
            ledger = await production_ledger()
            before = await ledger.snapshot()
            async with httpx.AsyncClient(follow_redirects=False) as client:
                config = ModelConfig.from_env()
                result = await multi_review(bundle,
                    DeepSeekReviewModel(config, client, ledger, work_package=WORK_PACKAGE),
                    DeepSeekEvidenceModel(config, client, ledger), trace=trace)
            result.update(budget_before=before, budget_after=await ledger.snapshot())
        else:
            result = await multi_review(bundle, ScriptedReviewModel(), ScriptedEvidenceModel(),
                                         trace=trace)
        result["material_unchanged"] = await service.get(identity, args.task) == bundle["snapshot"]
        if not result["material_unchanged"]:
            result["coordination"] = "stale_material_revision"
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
    parser.add_argument("--trace", type=Path, default=Path(".runtime/multi-review.trace.jsonl"))
    try:
        result = asyncio.run(run(parser.parse_args()), loop_factory=asyncio.SelectorEventLoop)
    except (ValueError, OSError, psycopg.Error, AccessDenied, InvalidTransition):
        parser.exit(2, "协同请求无法执行；检查任务归属与本地配置，连接详情已隐藏。\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
