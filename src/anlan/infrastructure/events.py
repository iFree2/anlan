"""Durable raw synthetic events; association never controls alarms."""
import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from anlan.collaboration.event_access import EventAccess
from anlan.common.errors import AccessDenied
from anlan.infrastructure.db import conninfo
from anlan.workflows.event_contracts import (
    EventConflict,
    Identifier,
    SourceBinding,
    digest,
    parse_event,
)
from anlan.workflows.events import admission


class EventStore:
    def __init__(self, dsn, *, clock=None, access_config=None):
        self.dsn = dsn
        self.clock = clock or (lambda: datetime.now(UTC))
        self.access = EventAccess(access_config)

    def now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event clock must be timezone aware")
        return value.astimezone(UTC)

    async def connect(self):
        return await AsyncConnection.connect(conninfo(self.dsn), row_factory=dict_row)

    async def initialize(self):
        async with await self.connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421106)")
            await conn.execute(files("anlan").joinpath("sql/005_events.sql").read_text(
                encoding="utf-8"), prepare=False)

    @staticmethod
    async def _stream_lock(conn, identity, source_id):
        key = json.dumps(["perception", identity.tenant_id, identity.user_id, source_id])
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))

    @staticmethod
    def _document(row):
        return row["document"] | {"result": row["result"]}

    async def _get(self, conn, identity, receipt_id, *, lock=False):
        storage_scope = await self.access.resource(conn, identity, receipt_id)
        cursor = await conn.execute(
            "SELECT document,result FROM anlan_v2.perception_events "
            "WHERE receipt_id=%s AND tenant_id=%s AND user_id=%s" +
            (" FOR UPDATE" if lock else ""),
            (receipt_id, storage_scope.tenant_id, storage_scope.user_id))
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("事件不存在或当前测试身份无权访问")
        return self._document(row)

    async def get(self, identity, receipt_id):
        async with await self.connect() as conn:
            return await self._get(conn, identity, receipt_id)

    @staticmethod
    async def _head(conn, identity, source_id):
        cursor = await conn.execute(
            "SELECT sequence,observed_at,receipt_id FROM anlan_v2.perception_heads "
            "WHERE tenant_id=%s AND user_id=%s AND source_id=%s",
            (identity.tenant_id, identity.user_id, source_id))
        return await cursor.fetchone()

    async def receive(self, identity, source_id, payload, source=None, *, conn=None,
                      storage_scope=None):
        if storage_scope is not None:
            if conn is None or source is None:
                raise AccessDenied('共享接入必须复用授权任务连接')
            resolved = await self.access.scope(conn, identity, source.task_id, 'run_event_review')
            if resolved != storage_scope:
                raise AccessDenied('资源范围不一致')
        scope = storage_scope or identity
        source_id = TypeAdapter(Identifier).validate_python(source_id)
        if source is not None:
            source = SourceBinding.model_validate(source)
            if source.identity != scope or source.source_id != source_id:
                raise AccessDenied("来源不属于当前可信接入身份")
        event = parse_event(payload)
        # Store validated original JSON values, not a model rewrite of the raw alarm.
        raw = json.loads(json.dumps(payload, allow_nan=False))
        body_hash = digest(raw)
        now = self.now()
        if conn is None:
            async with await self.connect() as own_conn:
                return await self._receive(own_conn, identity, source_id, event, raw,
                                           body_hash, source, now)
        return await self._receive(conn, scope, source_id, event, raw, body_hash, source, now,
                                   actor=identity)

    async def _receive(self, conn, identity, source_id, event, raw, body_hash, source, now,
                       *, actor=None):
        async with conn.transaction():
            await self._stream_lock(conn, identity, source_id)
            cursor = await conn.execute(
                "SELECT document,result,body_hash FROM anlan_v2.perception_events "
                "WHERE tenant_id=%s AND user_id=%s AND source_id=%s AND event_id=%s",
                (identity.tenant_id, identity.user_id, source_id, event.event_id))
            previous = await cursor.fetchone()
            if previous:
                if previous["body_hash"] != body_hash:
                    raise EventConflict("同一事件ID的原始内容不可覆盖")
                return self._document(previous)
            reason = admission(event, source, now)
            head = await self._head(conn, identity, source_id)
            if reason == "pending" and head:
                if event.sequence == head["sequence"]:
                    reason = "sequence_conflict"
                elif event.sequence < head["sequence"] or event.observed_at < head["observed_at"]:
                    reason = "out_of_order"
            receipt_id = str(uuid4())
            binding = source.model_dump(mode="json") if source else None
            document = {"schema_version": "event-receipt-v1", "data_origin": "SYNTHETIC",
                        "receipt_id": receipt_id, "source_id": source_id,
                        "identity": identity.model_dump(), "raw": raw, "body_hash": body_hash,
                        "binding": binding, "binding_hash": digest(binding) if binding else None,
                        "received_at": now.isoformat(), "admission": reason}
            document['actor'] = (actor or identity).model_dump()
            result = None if reason == "pending" else {
                "status": reason, "processed_at": now.isoformat()}
            await conn.execute(
                "INSERT INTO anlan_v2.perception_events "
                "(receipt_id,tenant_id,user_id,source_id,event_id,body_hash,document,result) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (receipt_id, identity.tenant_id, identity.user_id, source_id, event.event_id,
                 body_hash, Jsonb(document), Jsonb(result) if result else None))
            if reason == "pending":
                await conn.execute(
                    "INSERT INTO anlan_v2.perception_heads "
                    "(tenant_id,user_id,source_id,sequence,observed_at,receipt_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,user_id,source_id) "
                    "DO UPDATE SET sequence=excluded.sequence,observed_at=excluded.observed_at,"
                    "receipt_id=excluded.receipt_id",
                    (identity.tenant_id, identity.user_id, source_id, event.sequence,
                     event.observed_at, receipt_id))
        return document | {"result": result}

    async def finish(self, conn, identity, receipt_id, status):
        """Caller holds the task lock on THIS connection; never opens a write connection."""
        async with conn.transaction():
            scope = await self.access.resource(conn, identity, receipt_id,
                                               action='run_event_review')
            row = await self._get(conn, identity, receipt_id)
            await self._stream_lock(conn, scope, row["source_id"])
            row = await self._get(conn, identity, receipt_id, lock=True)
            if row["result"] is not None:
                return row
            event = parse_event(row["raw"])
            source = SourceBinding.model_validate(row["binding"])
            now = self.now()
            head = await self._head(conn, scope, row["source_id"])
            current = admission(event, source, now)
            if current != "pending":
                status = current
            elif head is None or head["receipt_id"] != receipt_id:
                status = "superseded_event"
            result = {"status": status, "processed_at": now.isoformat()}
            if status == "linked":
                result.update(task_id=source.task_id, revision=source.revision,
                              run_id=source.run_id, binding_hash=row["binding_hash"])
            await conn.execute(
                "UPDATE anlan_v2.perception_events SET result=%s "
                "WHERE receipt_id=%s AND tenant_id=%s AND user_id=%s AND result IS NULL",
                (Jsonb(result), receipt_id, scope.tenant_id, scope.user_id))
            return row | {"result": result}
