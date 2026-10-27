"""Deterministic commands: one task lock, real checkpoint, one short PG transaction."""

import asyncio
import json
from typing import Annotated
from uuid import uuid4

from psycopg.types.json import Jsonb
from pydantic import AfterValidator, Field, StringConstraints

from anlan.collaboration.access import project_materials
from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity, StrictModel
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.infrastructure.preflight import PrecheckStore
from anlan.preflight.catalog import CatalogService
from anlan.preflight.service import PreflightService, source_signature
from anlan.workflows.material_contracts import Application


def _nonblank(value):
    if not value.strip():
        raise ValueError("Text must not be blank")
    return value


# Keep the exact validated text: even whitespace changes are payload conflicts.
CommandText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=500), AfterValidator(_nonblank)
]


class Command(StrictModel):
    request_id: CommandText
    expected_application_version: int = Field(strict=True, ge=1)
    expected_material_revision: int = Field(strict=True, ge=1)


class SubmitCommand(Command):
    reviewer_user_id: CommandText
    expected_binding_revision: int | None = Field(default=None, strict=True, ge=1)


class RequestChangesCommand(Command):
    questions: list[CommandText] = Field(min_length=1, max_length=20)


class ResubmitCommand(Command):
    reply: CommandText
    expected_binding_revision: int | None = Field(default=None, strict=True, ge=1)


class CompleteReviewCommand(Command):
    conclusion: CommandText
    expected_binding_revision: int | None = Field(default=None, strict=True, ge=1)
    expected_check_id: CommandText | None = None
    applied_knowledge_citation_ids: list[CommandText] = Field(default_factory=list, max_length=3)


COMMANDS = {
    "submit": SubmitCommand,
    "request_changes": RequestChangesCommand,
    "resubmit": ResubmitCommand,
    "complete_review": CompleteReviewCommand,
}


class CollaborationService:
    def __init__(self, dsn, config, service_context_factory):
        self.store = CollaborationStore(dsn)
        self.prechecks = PrecheckStore(dsn)
        self.preflight = PreflightService(dsn, config, service_context_factory)
        self.config, self.service_context_factory = config, service_context_factory

    async def list(self, actor):
        return {
            "items": await self.store.list(actor, self.config.collaboration_role(actor)),
            "limit": 100,
        }

    @staticmethod
    async def _bounded_lock(operation):
        # Retrying only lock acquisition cannot replay a partially committed command.
        for attempt in range(11):
            try:
                return await operation()
            except TaskBusy:
                if attempt == 10:
                    raise
                await asyncio.sleep(0.05)

    async def get(self, actor, task_id):
        return await self._bounded_lock(lambda: self._get(actor, task_id))

    async def _get(self, actor, task_id):
        role = self.config.collaboration_role(actor)
        async with self.service_context_factory() as workflow:
            async with workflow._registry.locked(actor, task_id, action="read") as record:
                conn = workflow._registry.conn
                application = await self.store.get(actor, role, task_id, conn=conn)
                state = (await workflow._snapshot(record)).values
                if not state:
                    raise InvalidTransition("任务尚未写入 checkpoint；请执行 recover")
                policy = await self.prechecks.ensure_policy(actor.tenant_id, task_id, conn=conn)
                binding = await self.prechecks.get_binding(actor.tenant_id, task_id, conn=conn)
                job = await self.prechecks.latest(actor.tenant_id, task_id, conn=conn)
                view = {
                    "required": policy.required,
                    "legacy_completed": policy.legacy_completed,
                    "binding_revision": binding.binding_revision if binding else None,
                    "status": "unbound" if binding is None else "not_checked",
                    "clock_mode": "fixed_replay" if self.config.as_of else "wall_clock",
                    "as_of": self.config.as_of.isoformat() if self.config.as_of else None,
                }
                if job:
                    view.update(status=job["status"], check_id=job["check_id"])
                    if job["result"]:
                        view["issues"] = job["result"].get("issues", [])
                    try:
                        await CatalogService(self.config).validate(actor, binding.references)
                        async with conn.transaction():
                            current = await self.preflight.current(
                                conn, actor, application, state, binding, job
                            )
                            failed = (
                                job["result"] is not None
                                and job["result"].get("execution_status") == "failed"
                            )
                            stale = (
                                bool(job["result"].get("stale"))
                                or not await self.preflight.inputs_current(
                                    conn, actor, application, state, binding, job
                                )
                                if failed
                                else bool(job["result"] is not None and not current)
                            )
                        view.update(
                            current=current,
                            stale=stale,
                            execution_status="failed" if failed else job["status"],
                            status=(
                                "failed"
                                if failed
                                else "ready"
                                if current and job["result"].get("ready")
                                else "gap"
                                if current
                                else "stale"
                            ),
                        )
                        if current:
                            view["evidence"] = job["result"]
                    except (AccessDenied, AttributeError):
                        view.update(current=False, status="unavailable")
                    if job["result"] is None:
                        view.update(current=False, status=job["status"])
                return {
                    "application": application,
                    "materials": project_materials(state),
                    "precheck": view,
                    "events": await self.store.events(conn, application),
                    "notice": "材料核查完成不代表作业批准或开工授权",
                }

    async def execute(self, actor, task_id, action, payload):
        return await self._bounded_lock(lambda: self._execute(actor, task_id, action, payload))

    async def _execute(self, actor, task_id, action, payload):
        if action not in COMMANDS:
            raise ValueError("Unknown collaboration action")
        command = COMMANDS[action].model_validate(payload)
        role = self.config.collaboration_role(actor)
        async with self.service_context_factory() as workflow:
            registry = workflow._registry
            async with registry.locked(actor, task_id, action="read") as record:
                conn = registry.conn
                async with conn.transaction():
                    # Serializes the actor/request namespace across DIFFERENT tasks,
                    # before any mutation. Task lock is always acquired first.
                    key = json.dumps([actor.tenant_id, actor.user_id, command.request_id])
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))", (key,)
                    )
                    application = await self.store.get(
                        actor, role, task_id, conn=conn, for_update=True
                    )
                    previous = await self.store.receipt(conn, actor, command.request_id)
                    if previous:
                        if (
                            previous["task_id"] != task_id
                            or previous["action"] != action
                            or previous["actor_role"] != role
                            or previous["expected_application_version"]
                            != command.expected_application_version
                            or previous["expected_material_revision"]
                            != command.expected_material_revision
                            or previous["payload"] != command.model_dump(mode="json")
                        ):
                            raise InvalidTransition("相同 request_id 的任务或完整载荷不同")
                        return previous["result"]
                    authorize(actor, role, application, action)
                    policy = await self.prechecks.ensure_policy(actor.tenant_id, task_id, conn=conn)
                    if not policy.required:
                        raise InvalidTransition("历史已完成申请不能重新执行协作命令")
                    workflow._config(record)
                    workflow._check_mode(record)
                    snapshot = await workflow._snapshot(record)
                    state = snapshot.values
                    if (
                        application.version != command.expected_application_version
                        or not state
                        or state["revision"] != command.expected_material_revision
                        or await registry.pending(task_id)
                        or snapshot.next
                        or snapshot.interrupts
                        or state["status"] != "awaiting_review"
                        or state.get("analysis", {}).get("semantic_status")
                        not in {"checked", "offline_not_checked"}
                        or state.get("analysis", {}).get("error")
                        or state.get("analysis", {}).get("issues")
                        or not all(
                            Application.model_validate(state["fields"]).model_dump().values()
                        )
                    ):
                        raise InvalidTransition("材料尚未完成、存在待恢复操作或确认版本已过期")
                    if action == "submit":
                        target = Identity(
                            tenant_id=actor.tenant_id, user_id=command.reviewer_user_id
                        )
                        if (
                            target.user_id != command.reviewer_user_id
                            or target not in self.config.collaboration_reviewers(actor)
                        ):
                            raise AccessDenied("指定核查人不在当前可信名单")
                    binding = await self.prechecks.get_binding(actor.tenant_id, task_id, conn=conn)
                    if action in {"submit", "resubmit"}:
                        binding = await self.preflight.require_binding(
                            actor, task_id, command.expected_binding_revision, conn
                        )
                    if action == "resubmit" and state["revision"] <= (
                        application.submitted_material_revision or 0
                    ):
                        cycle = await (
                            await conn.execute(
                                "SELECT * FROM anlan_v2.precheck_cycles "
                                "WHERE task_id=%s ORDER BY application_version DESC LIMIT 1",
                                (task_id,),
                            )
                        ).fetchone()
                        latest = await self.prechecks.latest(actor.tenant_id, task_id, conn=conn)
                        source_changed = bool(
                            cycle
                            and latest
                            and latest["result"]
                            and source_signature(latest["result"]) != cycle["baseline"]
                            and await self.preflight.current(
                                conn, actor, application, state, binding, latest
                            )
                        )
                        if not cycle or (
                            binding.binding_revision == cycle["binding_revision"]
                            and not source_changed
                        ):
                            raise InvalidTransition("重提需要材料、绑定或当前来源依据发生实质变化")
                    if action in {"request_changes", "complete_review"} and (
                        state["revision"] != application.submitted_material_revision
                    ):
                        raise InvalidTransition("当前材料与已提交材料版本不一致")
                    if action == "complete_review":
                        await self.preflight.complete(conn, actor, application, state, command)
                    updated = await self.store.transition(conn, application, action, command)
                    if action in {"submit", "resubmit"}:
                        job = await self.preflight.enqueue(
                            conn, actor, updated, state, binding, request_id=command.request_id
                        )
                    if action == "request_changes":
                        latest = await self.prechecks.latest(actor.tenant_id, task_id, conn=conn)
                        await conn.execute(
                            "INSERT INTO anlan_v2.precheck_cycles "
                            "(task_id,application_version,binding_revision,baseline) "
                            "VALUES (%s,%s,%s,%s)",
                            (
                                task_id,
                                updated.version,
                                binding.binding_revision if binding else 0,
                                Jsonb(source_signature(latest["result"]) if latest else None),
                            ),
                        )
                    event_id = uuid4().hex
                    public_payload = command.model_dump(
                        mode="json",
                        exclude={
                            "request_id",
                            "expected_application_version",
                            "expected_material_revision",
                        },
                    )
                    await self.store.append_event(
                        conn,
                        actor,
                        role,
                        updated,
                        action,
                        state["revision"],
                        public_payload,
                        event_id,
                    )
                    result = {
                        "application": updated.model_dump(mode="json"),
                        "event_id": event_id,
                        "notice": "材料核查完成不代表作业批准或开工授权",
                    }
                    if action in {"submit", "resubmit"}:
                        result["precheck_job_id"] = job["job_id"]
                    await self.store.save_receipt(
                        conn, actor, role, task_id, action, command, result
                    )
                    return result

    async def notifications(self, actor, *, after=0, limit=100):
        role = self.config.collaboration_role(actor)
        if role not in {"applicant", "safety_manager"}:
            raise AccessDenied("当前身份未启用协作角色")
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid inbox cursor or limit")
        async with self.store.connection() as conn:
            cursor = await conn.execute(
                "SELECT n.ordinal,e.event_id,e.task_id,e.actor_user_id,e.actor_role,e.action,"
                "e.material_revision,e.application_version,e.payload,e.created_at "
                "FROM anlan_v2.collaboration_notifications n "
                "JOIN anlan_v2.collaboration_events e ON e.tenant_id=n.tenant_id "
                "AND e.event_id=n.event_id WHERE n.tenant_id=%s AND n.recipient_user_id=%s "
                "AND n.ordinal>%s ORDER BY n.ordinal LIMIT %s",
                (actor.tenant_id, actor.user_id, after, limit),
            )
            rows = await cursor.fetchall()
            next_cursor = rows[-1]["ordinal"] if rows else after
            items = []
            for row in rows:
                try:
                    await self.store.get(actor, role, row["task_id"], conn=conn)
                except AccessDenied:
                    continue
                items.append(
                    {
                        "ordinal": row["ordinal"],
                        "event": {key: value for key, value in row.items() if key != "ordinal"},
                    }
                )
            return {"items": items, "next_cursor": next_cursor, "limit": limit}
