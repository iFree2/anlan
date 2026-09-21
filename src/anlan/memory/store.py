"""Small user-scoped synthetic preference store; no model writes or business authority."""

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.db import conninfo
from anlan.memory.contracts import Feedback, MemoryConflict


class MemoryStore:
    def __init__(self, dsn: str, *, clock=None):
        self._dsn = dsn
        self.clock = clock or (lambda: datetime.now(UTC))

    def now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Memory clock must be timezone aware")
        return value.astimezone(UTC)

    async def _connect(self):
        return await AsyncConnection.connect(conninfo(self._dsn), row_factory=dict_row)

    async def initialize(self):
        async with await self._connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421105)")
            await conn.execute("CREATE SCHEMA IF NOT EXISTS anlan_v2")
            await conn.execute(files("anlan").joinpath("sql/004_memory.sql").read_text(
                encoding="utf-8"), prepare=False)

    async def feedback(self, identity: Identity, payload: dict):
        source = Feedback.model_validate(payload)
        now = self.now()
        if not source.observed_at <= now < source.expires_at:
            raise ValueError("Feedback is future dated or expired")
        value = source.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode(
            "utf-8")).hexdigest()
        async with await self._connect() as conn:
            await conn.execute(
                "INSERT INTO anlan_v2.memory_feedback "
                "(tenant_id,user_id,source_ref,version,source_hash,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (identity.tenant_id, identity.user_id, source.source_ref, source.version,
                 digest, Jsonb(value)))
            saved = await self._source(conn, identity, source.source_ref, source.version)
            if saved["source_hash"] != digest:
                raise MemoryConflict("已有反馈版本的内容不可覆盖")
        return {"source_ref": source.source_ref, "version": source.version, "source_hash": digest}

    async def _source(self, conn, identity, source_ref, version):
        if type(version) is not int or version < 1:
            raise ValueError("Source version must be a positive integer")
        cursor = await conn.execute(
            "SELECT source_hash,payload FROM anlan_v2.memory_feedback "
            "WHERE tenant_id=%s AND user_id=%s AND source_ref=%s AND version=%s",
            (identity.tenant_id, identity.user_id, source_ref, version))
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("来源不存在或当前测试身份无权访问")
        return row

    def _source_fields(self, source, now):
        payload = Feedback.model_validate(source["payload"])
        if not payload.observed_at <= now < payload.expires_at:
            raise MemoryConflict("来源尚未生效或已过期")
        return {"key": payload.key, "value": payload.value, "source_ref": payload.source_ref,
                "source_version": payload.version, "source_hash": source["source_hash"],
                "expires_at": payload.expires_at.isoformat()}

    async def _save(self, conn, snapshot):
        await conn.execute("UPDATE anlan_v2.memories SET snapshot=%s WHERE memory_id=%s",
                           (Jsonb(snapshot), snapshot["memory_id"]))
        await conn.execute("INSERT INTO anlan_v2.memory_revisions "
                           "(memory_id,revision,snapshot) VALUES (%s,%s,%s)",
                           (snapshot["memory_id"], snapshot["revision"], Jsonb(snapshot)))

    async def propose(self, identity: Identity, source_ref: str, version: int):
        now = self.now()
        async with await self._connect() as conn:
            source = await self._source(conn, identity, source_ref, version)
            key = source["payload"]["key"]
            # Serialize even when the key has no row yet. The transaction owns the lock.
            lock_key = json.dumps(["memory", identity.tenant_id, identity.user_id, key])
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
            cursor = await conn.execute(
                "SELECT snapshot FROM anlan_v2.memories "
                "WHERE tenant_id=%s AND user_id=%s AND key=%s FOR UPDATE",
                (identity.tenant_id, identity.user_id, key))
            old = await cursor.fetchone()
            if old:
                snapshot = old["snapshot"]
                if snapshot["source_hash"] == source["source_hash"]:
                    return snapshot  # Replay returns present state, never an old cached candidate.
                raise MemoryConflict("此偏好已有记录；修正须使用当前revision和新来源")
            snapshot = {"data_origin": "SYNTHETIC", "memory_id": str(uuid4()),
                        "tenant_id": identity.tenant_id, "user_id": identity.user_id,
                        **self._source_fields(source, now), "status": "candidate", "revision": 1,
                        "created_at": now.isoformat(), "updated_at": now.isoformat(),
                        "operation": "propose"}
            await conn.execute("INSERT INTO anlan_v2.memories "
                               "(memory_id,tenant_id,user_id,key,snapshot) VALUES (%s,%s,%s,%s,%s)",
                               (snapshot["memory_id"], identity.tenant_id, identity.user_id,
                                key, Jsonb(snapshot)))
            await self._save(conn, snapshot)
        return snapshot

    async def _get(self, conn, identity, memory_id, *, lock=False):
        try:
            memory_id = str(UUID(memory_id))
        except (ValueError, TypeError, AttributeError):
            raise AccessDenied("记忆不存在或当前测试身份无权访问") from None
        cursor = await conn.execute(
            "SELECT snapshot FROM anlan_v2.memories "
            "WHERE memory_id=%s AND tenant_id=%s AND user_id=%s" + (" FOR UPDATE" if lock else ""),
            (memory_id, identity.tenant_id, identity.user_id))
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("记忆不存在或当前测试身份无权访问")
        return row["snapshot"]

    async def get(self, identity: Identity, memory_id: str):
        async with await self._connect() as conn:
            return await self._get(conn, identity, memory_id)

    async def history(self, identity: Identity, memory_id: str):
        async with await self._connect() as conn:
            await self._get(conn, identity, memory_id)
            cursor = await conn.execute("SELECT snapshot FROM anlan_v2.memory_revisions "
                                        "WHERE memory_id=%s ORDER BY revision", (memory_id,))
            return [row["snapshot"] for row in await cursor.fetchall()]

    async def list_active(self, identity: Identity):
        now = self.now()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                "SELECT snapshot FROM anlan_v2.memories WHERE tenant_id=%s AND user_id=%s "
                "AND snapshot->>'status'='active' "
                "AND (snapshot->>'updated_at')::timestamptz <= %s "
                "AND (snapshot->>'expires_at')::timestamptz > %s ORDER BY key",
                (identity.tenant_id, identity.user_id, now, now))
            return [row["snapshot"] for row in await cursor.fetchall()]

    async def change(self, identity: Identity, memory_id: str, expected_revision: int,
                     operation: str, *, source_ref=None, source_version=None):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        now = self.now()
        async with await self._connect() as conn:
            old = await self._get(conn, identity, memory_id, lock=True)
            if old["revision"] != expected_revision or old["status"] == "deleted":
                raise MemoryConflict("旧revision或已删除记忆不可修改")
            if now < datetime.fromisoformat(old["updated_at"]):
                raise MemoryConflict("写入时钟不能倒退")
            expired = now >= datetime.fromisoformat(old["expires_at"])
            new = {**old, "revision": old["revision"] + 1, "updated_at": now.isoformat(),
                   "operation": operation}
            if operation == "correct":
                source = await self._source(conn, identity, source_ref, source_version)
                fields = self._source_fields(source, now)
                if fields["key"] != old["key"] or fields["source_hash"] == old["source_hash"]:
                    raise MemoryConflict("修正必须提供同键的新来源")
                # Inspect all history so an intermediate source cannot bypass the watermark.
                cursor = await conn.execute(
                    "SELECT 1 FROM anlan_v2.memory_revisions WHERE memory_id=%s "
                    "AND snapshot->>'source_ref'=%s "
                    "AND (snapshot->>'source_version')::integer >= %s LIMIT 1",
                    (memory_id, fields["source_ref"], fields["source_version"]))
                if await cursor.fetchone():
                    raise MemoryConflict("旧来源不可复活；请登记新的反馈版本")
                new.update(fields, status="candidate")
            elif operation == "delete":
                new["status"] = "deleted"
            elif operation == "expire" and expired and old["status"] in {
                    "candidate", "active", "conflicted"}:
                new["status"] = "expired"
            elif (not expired and operation in {"confirm", "reject"}
                  and old["status"] == "candidate"):
                new["status"] = "active" if operation == "confirm" else "rejected"
            elif not expired and operation == "conflict" and old["status"] == "active":
                new["status"] = "conflicted"
            else:
                raise MemoryConflict("记忆状态不允许此操作")
            await self._save(conn, new)
        return new
