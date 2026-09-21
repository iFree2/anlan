"""Synthetic local Memory administration; each invocation is a separate process."""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.db import database_url
from anlan.memory.store import MemoryStore


async def run(args):
    identity = Identity(tenant_id=args.tenant, user_id=args.user)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    store = MemoryStore(database_url(), clock=(lambda: as_of) if as_of else None)
    store.now()
    if args.command == "init":
        await store.initialize()
        return {"status": "memory_ready"}
    if args.command == "feedback":
        if args.file.stat().st_size > 16384:
            raise ValueError("Feedback file too large")
        return await store.feedback(identity, json.loads(args.file.read_text(encoding="utf-8-sig")))
    if args.command == "propose":
        return await store.propose(identity, args.source_ref, args.source_version)
    if args.command == "list":
        return await store.list_active(identity)
    if args.command == "show":
        return await store.get(identity, args.memory_id)
    if args.command == "history":
        return await store.history(identity, args.memory_id)
    return await store.change(identity, args.memory_id, args.revision, args.command,
                              source_ref=args.source_ref, source_version=args.source_version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "feedback", "propose", "list", "show",
                                            "history", "confirm", "reject", "correct",
                                            "conflict", "expire", "delete"])
    parser.add_argument("--tenant", default="synthetic-memory-demo")
    parser.add_argument("--user", default="safety-manager-demo")
    parser.add_argument("--as-of")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--source-ref")
    parser.add_argument("--source-version", type=int)
    parser.add_argument("--memory-id")
    parser.add_argument("--revision", type=int)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
    except (ValueError, AccessDenied, OSError, psycopg.Error, AttributeError):
        parser.exit(2, "记忆请求被拒绝；检查模拟身份、来源、时区、revision、状态或本地PG。\n")
    print(json.dumps({"data_origin": "SYNTHETIC", "clock_mode": "simulated" if args.as_of
                      else "system_utc", "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
