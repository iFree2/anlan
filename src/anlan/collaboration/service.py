"""Deterministic commands: one task lock, real checkpoint, one short PG transaction."""

import json
from typing import Annotated
from uuid import uuid4

from pydantic import AfterValidator, Field, StringConstraints

from anlan.collaboration.access import project_materials
from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity, StrictModel
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.workflows.material_contracts import Application


def _nonblank(value):
    if not value.strip():
        raise ValueError("Text must not be blank")
    return value


# Keep the exact validated text: even whitespace changes are payload conflicts.
CommandText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500),
                        AfterValidator(_nonblank)]


class Command(StrictModel):
    request_id: CommandText
    expected_application_version: int = Field(strict=True, ge=1)
    expected_material_revision: int = Field(strict=True, ge=1)


class SubmitCommand(Command):
    reviewer_user_id: CommandText


class RequestChangesCommand(Command):
    questions: list[CommandText] = Field(min_length=1, max_length=20)


class ResubmitCommand(Command):
    reply: CommandText


class CompleteReviewCommand(Command):
    conclusion: CommandText


COMMANDS = {"submit": SubmitCommand, "request_changes": RequestChangesCommand,
            "resubmit": ResubmitCommand, "complete_review": CompleteReviewCommand}


class CollaborationService:
    def __init__(self, dsn, config, service_context_factory):
        self.store = CollaborationStore(dsn)
        self.config, self.service_context_factory = config, service_context_factory

    async def list(self, actor):
        return {"items": await self.store.list(actor, self.config.collaboration_role(actor)),
                "limit": 100}

    async def get(self, actor, task_id):
        role = self.config.collaboration_role(actor)
        async with self.service_context_factory() as workflow:
            async with workflow._registry.locked(actor, task_id, action="read") as record:
                conn = workflow._registry.conn
                application = await self.store.get(actor, role, task_id, conn=conn)
                state = (await workflow._snapshot(record)).values
                if not state:
                    raise InvalidTransition('任务尚未写入 checkpoint；请执行 recover')
                return {"application": application, "materials": project_materials(state),
                        "events": await self.store.events(conn, application),
                        "notice": "材料核查完成不代表作业批准或开工授权"}

    async def execute(self, actor, task_id, action, payload):
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
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))", (key,))
                    application = await self.store.get(
                        actor, role, task_id, conn=conn, for_update=True)
                    previous = await self.store.receipt(conn, actor, command.request_id)
                    if previous:
                        if (previous["task_id"] != task_id or previous["action"] != action
                                or previous["actor_role"] != role
                                or previous["expected_application_version"] !=
                                command.expected_application_version
                                or previous["expected_material_revision"] !=
                                command.expected_material_revision
                                or previous["payload"] != command.model_dump(mode="json")):
                            raise InvalidTransition("相同 request_id 的任务或完整载荷不同")
                        return previous["result"]
                    authorize(actor, role, application, action)
                    workflow._config(record)
                    workflow._check_mode(record)
                    snapshot = await workflow._snapshot(record)
                    state = snapshot.values
                    if (application.version != command.expected_application_version
                            or not state or state["revision"] != command.expected_material_revision
                            or await registry.pending(task_id) or snapshot.next
                            or snapshot.interrupts or state["status"] != "awaiting_review"
                            or state.get("analysis", {}).get("semantic_status") not in
                            {"checked", "offline_not_checked"}
                            or state.get("analysis", {}).get("error")
                            or state.get("analysis", {}).get("issues")
                            or not all(Application.model_validate(state["fields"]).model_dump(
                            ).values())):
                        raise InvalidTransition("材料尚未完成、存在待恢复操作或确认版本已过期")
                    if action == "submit":
                        target = Identity(tenant_id=actor.tenant_id,
                                          user_id=command.reviewer_user_id)
                        if (target.user_id != command.reviewer_user_id
                                or target not in self.config.collaboration_reviewers(actor)):
                            raise AccessDenied("指定核查人不在当前可信名单")
                    if action == "resubmit" and state["revision"] <= (
                            application.submitted_material_revision or 0):
                        raise InvalidTransition("重提需要新的材料版本")
                    if action in {"request_changes", "complete_review"} and (
                            state["revision"] != application.submitted_material_revision):
                        raise InvalidTransition("当前材料与已提交材料版本不一致")
                    updated = await self.store.transition(conn, application, action, command)
                    event_id = uuid4().hex
                    public_payload = command.model_dump(mode="json", exclude={
                        "request_id", "expected_application_version", "expected_material_revision"})
                    await self.store.append_event(conn, actor, role, updated, action,
                                                  state["revision"], public_payload, event_id)
                    result = {"application": updated.model_dump(mode="json"),
                              "event_id": event_id,
                              "notice": "材料核查完成不代表作业批准或开工授权"}
                    await self.store.save_receipt(
                        conn, actor, role, task_id, action, command, result)
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
                (actor.tenant_id, actor.user_id, after, limit))
            rows = await cursor.fetchall()
            next_cursor = rows[-1]["ordinal"] if rows else after
            items = []
            for row in rows:
                try:
                    await self.store.get(actor, role, row["task_id"], conn=conn)
                except AccessDenied:
                    continue
                items.append({"ordinal": row["ordinal"], "event": {
                    key: value for key, value in row.items() if key != "ordinal"}})
            return {"items": items, "next_cursor": next_cursor, "limit": limit}
