"""Registration and authorized reads; business commands are added in a later batch."""

from importlib.resources import files

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from pydantic import TypeAdapter

from anlan.collaboration.contracts import ApplicationRecord, Role
from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied
from anlan.common.models import Identity, NonEmpty
from anlan.infrastructure.db import conninfo

_identifier = TypeAdapter(NonEmpty)


class CollaborationStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    async def _connect(self):
        return await AsyncConnection.connect(conninfo(self.dsn), row_factory=dict_row)

    async def initialize(self) -> None:
        """Requires the existing registry schema; never backfills or shares legacy tasks."""
        async with await self._connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421117)")
            await conn.execute(
                files("anlan").joinpath("sql/017_collaboration.sql").read_text(encoding="utf-8"),
                prepare=False,
            )

    async def ensure_draft(
        self, actor: Identity, role: Role | None, task_id: str,
    ) -> ApplicationRecord:
        task_id = _identifier.validate_python(task_id)
        if role != "applicant":
            raise AccessDenied("当前身份无权注册协作申请")
        async with await self._connect() as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    "SELECT task_id FROM anlan_v2.anlan_tasks "
                    "WHERE task_id=%s AND tenant_id=%s AND user_id=%s FOR KEY SHARE",
                    (task_id, actor.tenant_id, actor.user_id),
                )
                if await cursor.fetchone() is None:
                    raise AccessDenied("任务不存在或当前身份无权访问")
                await conn.execute(
                    "INSERT INTO anlan_v2.collaboration_applications "
                    "(task_id,tenant_id,applicant_user_id) VALUES (%s,%s,%s) "
                    "ON CONFLICT (task_id) DO NOTHING",
                    (task_id, actor.tenant_id, actor.user_id),
                )
                return await self._get(conn, actor, role, task_id)

    async def get(
        self, actor: Identity, role: Role | None, task_id: str,
    ) -> ApplicationRecord:
        task_id = _identifier.validate_python(task_id)
        async with await self._connect() as conn:
            return await self._get(conn, actor, role, task_id)

    async def list(
        self, actor: Identity, role: Role | None, limit: int = 100,
    ) -> list[ApplicationRecord]:
        if role not in {"applicant", "safety_manager"}:
            raise AccessDenied("当前身份未启用协作角色")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("application list limit must be between 1 and 100")
        predicate = (
            "applicant_user_id=%s" if role == "applicant" else
            "reviewer_user_id=%s AND applicant_user_id<>reviewer_user_id AND status<>'draft'"
        )
        async with await self._connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM anlan_v2.collaboration_applications WHERE tenant_id=%s AND "
                + predicate + " ORDER BY updated_at DESC,task_id LIMIT %s",
                (actor.tenant_id, actor.user_id, limit),
            )
            applications = [
                ApplicationRecord.model_validate(row) for row in await cursor.fetchall()
            ]
            for application in applications:
                authorize(actor, role, application, "read")
            return applications

    @staticmethod
    async def _get(conn, actor, role, task_id):
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.collaboration_applications WHERE tenant_id=%s AND task_id=%s",
            (actor.tenant_id, task_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("申请不存在或当前身份无权访问")
        application = ApplicationRecord.model_validate(row)
        authorize(actor, role, application, "read")
        return application
