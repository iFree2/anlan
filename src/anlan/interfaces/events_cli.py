"""Local SYNTHETIC event replay; CLI identity/binding are simulated host configuration."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity
from anlan.infrastructure.db import database_url
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.event_runtime import process_event
from anlan.workflows.event_contracts import SourceBinding


def read_json(path):
    if path.stat().st_size > 16384:
        raise ValueError("Event input exceeds 16 KiB")
    return json.loads(path.read_text(encoding="utf-8-sig"))


async def run(args):
    identity = Identity(tenant_id=args.tenant, user_id=args.user)
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    store = EventStore(database_url(), clock=lambda: now)
    store.now()
    if args.command == "init":
        await initialize_database(store.dsn)
        await store.initialize()
        return {"status": "initialized", "data_origin": "SYNTHETIC"}
    if args.command == "receive":
        source = SourceBinding.model_validate(read_json(args.binding)) if args.binding else None
        return await store.receive(identity, args.source, read_json(args.body), source)
    if args.command == "process":
        return await process_event(store.dsn, identity, args.receipt, clock=store.clock)
    return await store.get(identity, args.receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="synthetic-demo")
    parser.add_argument("--user", default="safety-manager-demo")
    parser.add_argument("--as-of", help="Explicit synthetic replay clock; timezone required")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    receive = commands.add_parser("receive")
    receive.add_argument("--source", required=True)
    receive.add_argument("--body", required=True, type=Path)
    receive.add_argument("--binding", type=Path, help="Trusted local host config, never event body")
    for command in ("show", "process"):
        commands.add_parser(command).add_argument("receipt")
    args = parser.parse_args()
    try:
        value = asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
    except (ValueError, OSError, psycopg.Error, AccessDenied, InvalidTransition, TaskBusy):
        parser.exit(2, "事件请求无法执行；检查身份、合同、版本和本地服务。连接详情已隐藏。\n")
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
