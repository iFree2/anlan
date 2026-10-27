"""Additive policies and bindings; writes use the caller's task-locked PG connection."""

from contextlib import asynccontextmanager
from importlib.resources import files

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.db import conninfo
from anlan.infrastructure.preflight_jobs import PrecheckJobs
from anlan.preflight.contracts import BindingRecord, PrecheckPolicy
from anlan.tools.contracts import FactReferences


class PrecheckStore(PrecheckJobs):
    def __init__(self, dsn):
        self.dsn = dsn

    async def _connect(self):
        return await AsyncConnection.connect(conninfo(self.dsn), row_factory=dict_row)

    @asynccontextmanager
    async def connection(self, conn=None):
        if conn is not None:
            yield conn
        else:
            async with await self._connect() as owned:
                yield owned

    async def initialize(self):
        """Schema only. Existing API composition never calls this B1 initializer."""
        async with self.connection() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421119)")
            await conn.execute(
                files("anlan")
                .joinpath("sql/019_preflight_bindings.sql")
                .read_text(encoding="utf-8"),
                prepare=False,
            )
            await conn.execute(
                files("anlan").joinpath("sql/020_preflight_checks.sql").read_text(encoding="utf-8"),
                prepare=False,
            )

    async def ensure_policy(self, tenant_id, task_id, *, conn=None) -> PrecheckPolicy:
        """Internal explicit registration from actual persisted stage, never a fake result.

        B2 must call this under its task lock when registering/upgrading applications.
        ON CONFLICT preserves subsequent policy decisions and historical provenance.
        """
        async with self.connection(conn) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    "SELECT status FROM anlan_v2.collaboration_applications "
                    "WHERE tenant_id=%s AND task_id=%s FOR SHARE",
                    (tenant_id, task_id),
                )
                application = await cursor.fetchone()
                if application is None:
                    raise AccessDenied("申请不存在或租户不符")
                legacy = application["status"] == "review_completed"
                await conn.execute(
                    "INSERT INTO anlan_v2.precheck_policies "
                    "(task_id,tenant_id,required,legacy_completed) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (task_id, tenant_id, not legacy, legacy),
                )
                cursor = await conn.execute(
                    "SELECT task_id,required,legacy_completed FROM anlan_v2.precheck_policies "
                    "WHERE tenant_id=%s AND task_id=%s",
                    (tenant_id, task_id),
                )
                return PrecheckPolicy.model_validate(await cursor.fetchone())

    @staticmethod
    def _binding(row):
        if row is None:
            return None
        return BindingRecord(
            task_id=row["task_id"],
            binding_revision=row["binding_revision"],
            material_revision_at_confirmation=row["material_revision_at_confirmation"],
            references=FactReferences(
                **{key: row[key] for key in ("worker_id", "qualification_type", "area_id")}
            ),
            confirmed_by=Identity(tenant_id=row["tenant_id"], user_id=row["confirmed_by_user_id"]),
            confirmed_at=row["confirmed_at"],
        )

    async def get_binding(self, tenant_id, task_id, *, conn=None) -> BindingRecord | None:
        """Internal lookup. Public reads must pass BindingService authorization first."""
        async with self.connection(conn) as conn:
            cursor = await conn.execute(
                "SELECT v.* FROM anlan_v2.precheck_binding_heads h "
                "JOIN anlan_v2.precheck_binding_versions v "
                "USING(tenant_id,task_id,binding_revision) "
                "WHERE h.tenant_id=%s AND h.task_id=%s",
                (tenant_id, task_id),
            )
            return self._binding(await cursor.fetchone())

    async def write_binding(self, conn, actor, task_id, command, current):
        references = FactReferences.model_validate(
            command.model_dump(include={"worker_id", "qualification_type", "area_id"})
        )
        if current is not None and current.references == references:
            return current
        revision = current.binding_revision + 1 if current else 1
        cursor = await conn.execute(
            "INSERT INTO anlan_v2.precheck_binding_versions "
            "(tenant_id,task_id,binding_revision,material_revision_at_confirmation,"
            "worker_id,qualification_type,area_id,confirmed_by_user_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                actor.tenant_id,
                task_id,
                revision,
                command.expected_material_revision,
                references.worker_id,
                references.qualification_type,
                references.area_id,
                actor.user_id,
            ),
        )
        binding = self._binding(await cursor.fetchone())
        await conn.execute(
            "INSERT INTO anlan_v2.precheck_binding_heads (tenant_id,task_id,binding_revision) "
            "VALUES (%s,%s,%s) ON CONFLICT (task_id) DO UPDATE "
            "SET binding_revision=EXCLUDED.binding_revision",
            (actor.tenant_id, task_id, revision),
        )
        return binding

    @staticmethod
    async def receipt(conn, actor, request_id):
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.precheck_binding_commands "
            "WHERE tenant_id=%s AND actor_user_id=%s AND request_id=%s",
            (actor.tenant_id, actor.user_id, request_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def save_receipt(conn, actor, task_id, command, result):
        await conn.execute(
            "INSERT INTO anlan_v2.precheck_binding_commands "
            "(tenant_id,actor_user_id,request_id,task_id,expected_material_revision,"
            "expected_binding_revision,binding_revision,payload,result) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                actor.tenant_id,
                actor.user_id,
                command.request_id,
                task_id,
                command.expected_material_revision,
                command.expected_binding_revision,
                result.binding_revision,
                Jsonb(command.model_dump(mode="json")),
                Jsonb(result.model_dump(mode="json")),
            ),
        )
