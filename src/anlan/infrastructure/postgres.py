"""Official checkpoint saver plus a small SQL registry in a dedicated schema."""


import asyncio
from contextlib import asynccontextmanager
from importlib.resources import files

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from anlan.common.errors import AccessDenied, TaskBusy
from anlan.common.models import Identity
from anlan.infrastructure.db import conninfo
from anlan.workflows.registry import Operation, TaskRecord


def checkpoint_serde():
    return JsonPlusSerializer(allowed_msgpack_modules=[], pickle_fallback=False)


async def initialize_database(dsn: str) -> None:
    async with await AsyncConnection.connect(conninfo(dsn), autocommit=True) as conn:
        await conn.execute("SELECT pg_advisory_lock(73421102)")
        try:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS anlan_v2")
            migration = files("anlan").joinpath("sql/001_registry.sql").read_text(encoding="utf-8")
            await conn.execute(migration, prepare=False)
            async with AsyncPostgresSaver.from_conn_string(
                conninfo(dsn), serde=checkpoint_serde()
            ) as saver:
                await saver.setup()
        finally:
            await conn.execute("SELECT pg_advisory_unlock(73421102)")


class PostgresRegistry:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn
        self._serial = asyncio.Lock()

    async def create(self, record: TaskRecord) -> None:
        async with self._serial:
            await self.conn.execute(
                "INSERT INTO anlan_tasks "
                "(task_id, thread_id, tenant_id, user_id, mode, contract_version, initial_state) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (record.task_id, record.thread_id, record.identity.tenant_id,
                 record.identity.user_id, record.mode, record.contract_version,
                 Jsonb(record.initial_state)),
            )

    @asynccontextmanager
    async def locked(self, identity: Identity, task_id: str):
        async with self._serial:
            cursor = await self.conn.execute(
                "SELECT * FROM anlan_tasks WHERE task_id=%s AND tenant_id=%s AND user_id=%s",
                (task_id, identity.tenant_id, identity.user_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise AccessDenied("任务不存在或当前测试身份无权访问")
            cursor = await self.conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired", (task_id,))
            if not (await cursor.fetchone())["acquired"]:
                raise TaskBusy("任务正在其他进程执行，请稍后读取状态")
            try:
                yield TaskRecord(row["task_id"], row["thread_id"], identity, row["mode"],
                                 row["initial_state"], row["contract_version"])
            finally:
                if not self.conn.closed:
                    await self.conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (task_id,))

    @staticmethod
    def _operation(row: dict | None) -> Operation | None:
        if row is None:
            return None
        return Operation(row["request_id"], row["run_id"], row["kind"], row["expected_revision"],
                         row["fields"], row["result"])

    async def operation(self, task_id: str, request_id: str) -> Operation | None:
        cursor = await self.conn.execute(
            "SELECT * FROM anlan_operations WHERE task_id=%s AND request_id=%s",
            (task_id, request_id),
        )
        return self._operation(await cursor.fetchone())

    async def pending(self, task_id: str) -> Operation | None:
        cursor = await self.conn.execute(
            "SELECT * FROM anlan_operations WHERE task_id=%s AND result IS NULL", (task_id,))
        return self._operation(await cursor.fetchone())

    async def reserve(self, task_id: str, operation: Operation) -> None:
        await self.conn.execute(
            "INSERT INTO anlan_operations "
            "(task_id, request_id, run_id, kind, expected_revision, fields) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (task_id, operation.request_id, operation.run_id, operation.kind,
             operation.expected_revision, Jsonb(operation.fields)),
        )

    async def complete(self, task_id: str, request_id: str, result: dict) -> None:
        await self.conn.execute(
            "UPDATE anlan_operations SET result=%s, completed_at=clock_timestamp() "
            "WHERE task_id=%s AND request_id=%s", (Jsonb(result), task_id, request_id),
        )

    async def history(self, task_id: str) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT request_id,run_id,kind,expected_revision, "
            "CASE WHEN result IS NULL THEN 'pending' ELSE 'completed' END AS status "
            "FROM anlan_operations WHERE task_id=%s ORDER BY started_at, request_id", (task_id,),
        )
        return await cursor.fetchall()
