"""PostgreSQL persistence for resumable, identity-scoped conversations."""

from contextlib import asynccontextmanager
from importlib.resources import files
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, TypeAdapter

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import NonEmpty
from anlan.infrastructure.db import conninfo

_identifier = TypeAdapter(NonEmpty)


def _document(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise TypeError("conversation documents must be mappings or Pydantic models")
    return value


def _text(value):
    if not isinstance(value, str):
        raise TypeError("message text must be a string")
    value = value.strip()
    if not value or len(value.encode("utf-8")) > 8192:
        raise ValueError("message text must contain between 1 and 8192 UTF-8 bytes")
    return value


class ConversationStore:
    def __init__(self, dsn):
        self.dsn = dsn

    async def connect(self):
        return await AsyncConnection.connect(conninfo(self.dsn), row_factory=dict_row)

    async def initialize(self) -> None:
        async with await self.connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421113)")
            await conn.execute(
                files("anlan")
                .joinpath("sql/013_conversations.sql")
                .read_text(encoding="utf-8"),
                prepare=False,
            )

    async def create(self, identity, request_id: str) -> dict:
        request_id = _identifier.validate_python(request_id)
        conversation_id = str(uuid4())
        async with await self.connect() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO anlan_v2.conversations "
                    "(conversation_id,tenant_id,user_id,create_request_id,status) "
                    "VALUES (%s,%s,%s,%s,'idle') ON CONFLICT "
                    "(tenant_id,user_id,create_request_id) DO NOTHING",
                    (
                        conversation_id,
                        identity.tenant_id,
                        identity.user_id,
                        request_id,
                    ),
                )
                cursor = await conn.execute(
                    "SELECT * FROM anlan_v2.conversations "
                    "WHERE tenant_id=%s AND user_id=%s AND create_request_id=%s",
                    (identity.tenant_id, identity.user_id, request_id),
                )
                row = await cursor.fetchone()
                return await self._snapshot(conn, row)

    async def list(self, identity, limit: int = 20) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("conversation list limit must be between 1 and 100")
        async with await self.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM anlan_v2.conversations "
                "WHERE tenant_id=%s AND user_id=%s ORDER BY updated_at DESC LIMIT %s",
                (identity.tenant_id, identity.user_id, limit),
            )
            return [await self._snapshot(conn, row) for row in await cursor.fetchall()]

    async def get(self, identity, conversation_id: str, *, conn=None, lock=False) -> dict:
        conversation_id = _identifier.validate_python(conversation_id)
        if conn is None:
            async with await self.connect() as own_conn:
                return await self.get(identity, conversation_id, conn=own_conn, lock=lock)
        row = await self._row(conn, identity, conversation_id, lock=lock)
        return await self._snapshot(conn, row)

    async def reserve_message(
        self,
        identity,
        conversation_id: str,
        request_id: str,
        expected_revision: int,
        text: str,
    ) -> dict:
        conversation_id = _identifier.validate_python(conversation_id)
        request_id = _identifier.validate_python(request_id)
        text = _text(text)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise TypeError("expected_revision must be an integer")
        payload = {"expected_revision": expected_revision, "text": text}
        async with await self.connect() as conn:
            async with conn.transaction():
                conversation = await self._row(conn, identity, conversation_id, lock=True)
                cursor = await conn.execute(
                    "SELECT * FROM anlan_v2.conversation_messages "
                    "WHERE conversation_id=%s AND request_id=%s",
                    (conversation_id, request_id),
                )
                previous = await cursor.fetchone()
                if previous is not None:
                    if previous["request_payload"] != payload:
                        raise InvalidTransition("相同request_id的消息载荷不同")
                    return self._message(previous)
                if conversation["revision"] != expected_revision:
                    raise InvalidTransition("conversation revision 已过时")
                cursor = await conn.execute(
                    "SELECT 1 FROM anlan_v2.conversation_messages "
                    "WHERE conversation_id=%s AND status='pending'",
                    (conversation_id,),
                )
                if await cursor.fetchone() is not None:
                    raise TaskBusy("会话仍有一条消息正在处理")
                message_id = str(uuid4())
                cursor = await conn.execute(
                    "INSERT INTO anlan_v2.conversation_messages "
                    "(message_id,conversation_id,request_id,role,text,status,request_payload) "
                    "VALUES (%s,%s,%s,'user',%s,'pending',%s) RETURNING *",
                    (message_id, conversation_id, request_id, text, Jsonb(payload)),
                )
                message = self._message(await cursor.fetchone())
                await conn.execute(
                    "UPDATE anlan_v2.conversations SET revision=revision+1,"
                    "updated_at=clock_timestamp() WHERE conversation_id=%s",
                    (conversation_id,),
                )
                return message

    async def save_route(
        self, identity, conversation_id, message_id, proposal, decision
    ) -> None:
        proposal, decision = _document(proposal), _document(decision)
        classifier_version = _identifier.validate_python(proposal.get("classifier_version"))
        async with await self.connect() as conn:
            async with conn.transaction():
                await self._row(conn, identity, conversation_id, lock=True)
                await self._owned_message(conn, conversation_id, message_id)
                cursor = await conn.execute(
                    "SELECT proposal,decision,classifier_version "
                    "FROM anlan_v2.conversation_routes WHERE message_id=%s",
                    (message_id,),
                )
                previous = await cursor.fetchone()
                if previous is not None:
                    if previous != {
                        "proposal": proposal,
                        "decision": decision,
                        "classifier_version": classifier_version,
                    }:
                        raise InvalidTransition("消息路由结果不可覆盖")
                    return
                await conn.execute(
                    "INSERT INTO anlan_v2.conversation_routes "
                    "(message_id,proposal,decision,classifier_version) VALUES (%s,%s,%s,%s)",
                    (message_id, Jsonb(proposal), Jsonb(decision), classifier_version),
                )

    async def set_pending_intent(
        self, identity, conversation_id, message_id, candidate
    ) -> dict:
        candidate = _document(candidate)
        async with await self.connect() as conn:
            async with conn.transaction():
                await self._row(conn, identity, conversation_id, lock=True)
                await self._owned_message(conn, conversation_id, message_id)
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 AS revision "
                    "FROM anlan_v2.pending_intents WHERE conversation_id=%s",
                    (conversation_id,),
                )
                revision = (await cursor.fetchone())["revision"]
                await conn.execute(
                    "UPDATE anlan_v2.pending_intents SET status='superseded' "
                    "WHERE conversation_id=%s AND status='pending'",
                    (conversation_id,),
                )
                intent_id = str(uuid4())
                cursor = await conn.execute(
                    "INSERT INTO anlan_v2.pending_intents "
                    "(intent_id,conversation_id,source_message_id,revision,status,candidate) "
                    "VALUES (%s,%s,%s,%s,'pending',%s) RETURNING *",
                    (intent_id, conversation_id, message_id, revision, Jsonb(candidate)),
                )
                pending = self._pending(await cursor.fetchone())
                await conn.execute(
                    "UPDATE anlan_v2.conversations SET status='pending_confirmation',"
                    "pending_intent_id=%s,updated_at=clock_timestamp() "
                    "WHERE conversation_id=%s",
                    (intent_id, conversation_id),
                )
                return pending

    async def bind_task(
        self, identity, conversation_id, expected_revision, task_id
    ) -> dict:
        task_id = _identifier.validate_python(task_id)
        async with await self.connect() as conn:
            async with conn.transaction():
                conversation = await self._row(conn, identity, conversation_id, lock=True)
                if conversation["revision"] != expected_revision:
                    raise InvalidTransition("conversation revision 已过时")
                if conversation["pending_intent_id"]:
                    await conn.execute(
                        "UPDATE anlan_v2.pending_intents SET status='confirmed' "
                        "WHERE intent_id=%s AND conversation_id=%s AND status='pending'",
                        (conversation["pending_intent_id"], conversation_id),
                    )
                await conn.execute(
                    "UPDATE anlan_v2.conversations SET status='active_hot_work',"
                    "active_task_id=%s,pending_intent_id=NULL,updated_at=clock_timestamp() "
                    "WHERE conversation_id=%s",
                    (task_id, conversation_id),
                )
                return await self.get(identity, conversation_id, conn=conn)

    async def finish_message(
        self, identity, conversation_id, message_id, result
    ) -> dict:
        return await self._complete_message(
            identity, conversation_id, message_id, "completed", _document(result)
        )

    async def fail_message(
        self, identity, conversation_id, message_id, category
    ) -> dict:
        category = _identifier.validate_python(category)
        return await self._complete_message(
            identity,
            conversation_id,
            message_id,
            "failed",
            {"error_category": category},
        )

    @asynccontextmanager
    async def locked(self, identity, conversation_id):
        conversation_id = _identifier.validate_python(conversation_id)
        async with await self.connect() as conn:
            await self._row(conn, identity, conversation_id)
            cursor = await conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired",
                ("conversation:" + conversation_id,),
            )
            if not (await cursor.fetchone())["acquired"]:
                raise TaskBusy("会话正在其他进程处理")
            try:
                yield conn
            finally:
                if not conn.closed:
                    await conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                        ("conversation:" + conversation_id,),
                    )

    async def _complete_message(
        self, identity, conversation_id, message_id, status, result
    ) -> dict:
        async with await self.connect() as conn:
            async with conn.transaction():
                await self._row(conn, identity, conversation_id, lock=True)
                message = await self._owned_message(conn, conversation_id, message_id)
                if message["status"] != "pending":
                    if message["status"] == status and message["result"] == result:
                        return self._message(message)
                    raise InvalidTransition("消息已完成且结果不可覆盖")
                cursor = await conn.execute(
                    "UPDATE anlan_v2.conversation_messages SET status=%s,result=%s,"
                    "completed_at=clock_timestamp() WHERE message_id=%s RETURNING *",
                    (status, Jsonb(result), message_id),
                )
                await conn.execute(
                    "UPDATE anlan_v2.conversations SET updated_at=clock_timestamp() "
                    "WHERE conversation_id=%s",
                    (conversation_id,),
                )
                return self._message(await cursor.fetchone())

    @staticmethod
    async def _row(conn, identity, conversation_id, *, lock=False):
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.conversations "
            "WHERE conversation_id=%s AND tenant_id=%s AND user_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (conversation_id, identity.tenant_id, identity.user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("会话不存在或当前身份无权访问")
        return row

    @staticmethod
    async def _owned_message(conn, conversation_id, message_id):
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.conversation_messages "
            "WHERE message_id=%s AND conversation_id=%s",
            (message_id, conversation_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("消息不存在或不属于当前会话")
        return row

    async def _snapshot(self, conn, row):
        conversation_id = row["conversation_id"]
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.conversation_messages "
            "WHERE conversation_id=%s ORDER BY ordinal",
            (conversation_id,),
        )
        messages = [self._message(item) for item in await cursor.fetchall()]
        cursor = await conn.execute(
            "SELECT r.* FROM anlan_v2.conversation_routes r "
            "JOIN anlan_v2.conversation_messages m ON m.message_id=r.message_id "
            "WHERE m.conversation_id=%s ORDER BY m.ordinal",
            (conversation_id,),
        )
        routes = [self._route(item) for item in await cursor.fetchall()]
        pending = None
        if row["pending_intent_id"] is not None:
            cursor = await conn.execute(
                "SELECT * FROM anlan_v2.pending_intents "
                "WHERE intent_id=%s AND conversation_id=%s AND status='pending'",
                (row["pending_intent_id"], conversation_id),
            )
            pending_row = await cursor.fetchone()
            if pending_row is None:
                raise InvalidTransition("会话引用了不存在的待确认意图")
            pending = self._pending(pending_row)
        return {
            "conversation_id": conversation_id,
            "create_request_id": row["create_request_id"],
            "status": row["status"],
            "revision": row["revision"],
            "active_task_id": row["active_task_id"],
            "pending_intent": pending,
            "messages": messages,
            "routes": routes,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _message(row):
        return {
            key: row[key]
            for key in (
                "message_id",
                "request_id",
                "ordinal",
                "role",
                "text",
                "status",
                "request_payload",
                "result",
                "created_at",
                "completed_at",
            )
        }

    @staticmethod
    def _pending(row):
        return {
            key: row[key]
            for key in (
                "intent_id",
                "source_message_id",
                "revision",
                "status",
                "candidate",
                "created_at",
            )
        }

    @staticmethod
    def _route(row):
        return {
            key: row[key]
            for key in (
                "message_id",
                "proposal",
                "decision",
                "classifier_version",
                "created_at",
            )
        }
