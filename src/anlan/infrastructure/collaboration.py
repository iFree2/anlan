"""Collaboration persistence; mutations reuse the caller's locked transaction connection."""

import json
from contextlib import asynccontextmanager
from importlib.resources import files

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
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

    @asynccontextmanager
    async def connection(self, conn=None):
        if conn is not None:
            yield conn
        else:
            async with await self._connect() as owned:
                yield owned

    async def initialize(self) -> None:
        """Requires the existing registry schema; never backfills or shares legacy tasks."""
        async with await self._connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421117)")
            await conn.execute(
                files("anlan").joinpath("sql/017_collaboration.sql").read_text(encoding="utf-8"),
                prepare=False,
            )

    async def ensure_draft(
        self, actor: Identity, role: Role | None, task_id: str, *, conn=None,
    ) -> ApplicationRecord:
        task_id = _identifier.validate_python(task_id)
        if role != "applicant":
            raise AccessDenied("当前身份无权注册协作申请")
        async with self.connection(conn) as conn:
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
                    "ON CONFLICT DO NOTHING",
                    (task_id, actor.tenant_id, actor.user_id),
                )
                return await self._get(conn, actor, role, task_id)

    async def get(
        self, actor: Identity, role: Role | None, task_id: str, *, conn=None, for_update=False,
    ) -> ApplicationRecord:
        task_id = _identifier.validate_python(task_id)
        async with self.connection(conn) as conn:
            return await self._get(conn, actor, role, task_id, for_update=for_update)

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
    async def _get(conn, actor, role, task_id, *, for_update=False):
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.collaboration_applications WHERE tenant_id=%s AND task_id=%s"
            + (" FOR UPDATE" if for_update else ""),
            (actor.tenant_id, task_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("申请不存在或当前身份无权访问")
        application = ApplicationRecord.model_validate(row)
        authorize(actor, role, application, "read")
        return application

    @staticmethod
    async def receipt(conn, actor, request_id):
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.collaboration_commands "
            "WHERE tenant_id=%s AND actor_user_id=%s AND request_id=%s",
            (actor.tenant_id, actor.user_id, request_id))
        return await cursor.fetchone()

    @staticmethod
    async def save_receipt(conn, actor, role, task_id, action, command, result):
        await conn.execute(
            "INSERT INTO anlan_v2.collaboration_commands "
            "(tenant_id,actor_user_id,request_id,task_id,action,actor_role,"
            "expected_application_version,expected_material_revision,payload,result) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (actor.tenant_id, actor.user_id, command.request_id, task_id, action, role,
             command.expected_application_version, command.expected_material_revision,
             Jsonb(command.model_dump(mode="json")), Jsonb(result)))

    @staticmethod
    async def transition(conn, application, action, command):
        status = {"submit": "under_review", "request_changes": "changes_requested",
                  "resubmit": "under_review", "complete_review": "review_completed"}[action]
        reviewer = (command.reviewer_user_id if action == "submit"
                    else application.reviewer_user_id)
        submitted = (command.expected_material_revision if action in {"submit", "resubmit"}
                     else application.submitted_material_revision)
        completed = command.expected_material_revision if action == "complete_review" else None
        cursor = await conn.execute(
            "UPDATE anlan_v2.collaboration_applications SET status=%s,version=version+1,"
            "reviewer_user_id=%s,submitted_material_revision=%s,completed_material_revision=%s,"
            "updated_at=clock_timestamp() WHERE task_id=%s AND version=%s RETURNING *",
            (status, reviewer, submitted, completed, application.task_id, application.version))
        return ApplicationRecord.model_validate(await cursor.fetchone())

    @staticmethod
    async def append_event(conn, actor, role, application, action, revision, payload, event_id):
        await conn.execute(
            "INSERT INTO anlan_v2.collaboration_events "
            "(event_id,tenant_id,task_id,actor_user_id,actor_role,action,material_revision,"
            "application_version,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (event_id, actor.tenant_id, application.task_id, actor.user_id, role, action,
             revision, application.version, Jsonb(payload)))
        recipient = (application.reviewer_user_id if role == "applicant"
                     else application.applicant_user_id)
        # Identity ordinals are allocated before commit. Serialize each inbox until
        # this caller-owned transaction ends, so a later visible cursor cannot skip
        # a lower ordinal that is still uncommitted on another task.
        inbox_key = json.dumps(["collaboration-notification-v1", actor.tenant_id, recipient])
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 2))", (inbox_key,))
        await conn.execute(
            "INSERT INTO anlan_v2.collaboration_notifications "
            "(tenant_id,recipient_user_id,event_id) VALUES (%s,%s,%s)",
            (actor.tenant_id, recipient, event_id))

    @staticmethod
    async def events(conn, application):
        cursor = await conn.execute(
            "SELECT event_id,task_id,actor_user_id,actor_role,action,material_revision,"
            "application_version,payload,created_at FROM anlan_v2.collaboration_events "
            "WHERE tenant_id=%s AND task_id=%s "
            "ORDER BY application_version,created_at,event_id LIMIT 100",
            (application.tenant_id, application.task_id))
        return await cursor.fetchall()
