"""SYNTHETIC perception review and feedback; host identities are simulated locally."""

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetError
from anlan.infrastructure.db import database_url
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.live import production_ledger
from anlan.infrastructure.perception import PerceptionStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.events_cli import read_json
from anlan.interfaces.perception_runtime import PerceptionRuntime
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.knowledge.tool import UnavailableKnowledgeStore
from anlan.llm.config import ModelConfig
from anlan.llm.perception import DeepSeekPerceptionModel, ScriptedPerceptionModel
from anlan.memory.store import MemoryStore
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer


async def run(args):
    identity = Identity(tenant_id=args.tenant, user_id=args.user)
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    runtime = PerceptionRuntime(database_url(), clock=lambda: now)
    runtime.events.now()
    if args.command == "init":
        await initialize_database(runtime.dsn)
        await EventStore(runtime.dsn).initialize()
        await PerceptionStore(runtime.dsn).initialize()
        await MemoryStore(runtime.dsn).initialize()
        return {"status": "initialized", "data_origin": "SYNTHETIC"}
    if args.command == "show":
        return await runtime.get(identity, args.review)
    if args.command == "recover":
        return await runtime.recover(identity, args.review)
    if args.command == "feedback":
        return await runtime.feedback(
            identity, args.review, args.revision, args.decision, request_id=args.request_id
        )
    event = await runtime.events.get(identity, args.receipt)
    if event["binding"] is None:
        raise InvalidTransition("未知来源不能重核")
    async with postgres_service(runtime.dsn, OfflineAnalyzer()) as service:
        await service.get(identity, event["binding"]["task_id"])
    # Identity/ownership above precede dependency setup and any credential read.
    try:
        knowledge = KnowledgeStore(runtime.dsn, await LocalEmbeddings.create(), clock=runtime.clock)
    except Exception:
        knowledge = UnavailableKnowledgeStore(runtime.clock)
    runtime.tools = FactTools(args.facts_dir, clock=runtime.clock)
    runtime.knowledge = knowledge
    runtime.memory = MemoryStore(runtime.dsn, clock=runtime.clock)
    runtime.model = ScriptedPerceptionModel()
    async with AsyncExitStack() as stack:
        if args.mode == "deepseek":
            ledger = await production_ledger()
            config = ModelConfig.from_env()
            client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
            runtime.model = DeepSeekPerceptionModel(config, client, ledger)
        return await runtime.review(
            identity, args.receipt, read_json(args.refs_file), request_id=args.request_id
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="synthetic-p5-replay")
    parser.add_argument("--user", default="safety-manager-demo")
    parser.add_argument("--as-of", help="Explicit SYNTHETIC replay clock")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    review = commands.add_parser("review")
    review.add_argument("receipt")
    review.add_argument("--refs-file", type=Path, required=True)
    review.add_argument("--request-id", required=True)
    review.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    review.add_argument("--facts-dir", type=Path, default=Path("examples/synthetic/facts-v1"))
    for name in ("show", "recover", "feedback"):
        sub = commands.add_parser(name)
        sub.add_argument("review")
        if name == "feedback":
            sub.add_argument("--revision", type=int, required=True)
            sub.add_argument("--request-id", required=True)
            sub.add_argument(
                "--decision",
                required=True,
                choices=["confirmed_event", "disputed_event", "needs_verification"],
            )
    args = parser.parse_args()
    try:
        value = asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
    except (
        ValueError,
        OSError,
        psycopg.Error,
        AccessDenied,
        InvalidTransition,
        TaskBusy,
        BudgetError,
    ):
        parser.exit(2, "感知重核无法执行；检查身份、当前版本与本地配置，连接详情已隐藏。\n")
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
