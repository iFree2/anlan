"""Resumable latest snapshots; not a token stream or a lossless event-history queue."""

import asyncio
import hashlib
import json
from time import monotonic

from anlan.common.errors import TaskBusy


def snapshot_id(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def snapshot_stream(initial, read, last_id, disconnected, *, poll_seconds=0.25):
    value, heartbeat = initial, monotonic()
    while not await disconnected():
        current_id = snapshot_id(value)
        if current_id != last_id:
            data = json.dumps(value, ensure_ascii=False)
            yield f"id: {current_id}\nevent: snapshot\ndata: {data}\n\n"
            last_id, heartbeat = current_id, monotonic()
        elif monotonic() - heartbeat >= 5:
            yield ": keep-alive\n\n"
            heartbeat = monotonic()
        await asyncio.sleep(poll_seconds)
        try:
            value = await read()
        except TaskBusy:
            continue
        except Exception:
            yield 'event: error\ndata: {"error":"snapshot_unavailable"}\n\n'
            return
