"""Explicit object confirmation under the real registry authorization/task lock."""

import json

from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.infrastructure.preflight import PrecheckStore
from anlan.preflight.catalog import CatalogService
from anlan.preflight.contracts import BindingCommand, BindingRecord


class BindingService:
    def __init__(self, dsn, config, service_context_factory):
        self.store = PrecheckStore(dsn)
        self.applications = CollaborationStore(dsn)
        self.config, self.service_context_factory = config, service_context_factory

    async def catalog(self, actor, task_id):
        async with self.service_context_factory() as workflow:
            async with workflow._registry.locked(actor, task_id, action="read"):
                await self.applications.get(actor, self.config.collaboration_role(actor), task_id,
                                            conn=workflow._registry.conn)
                return await CatalogService(self.config).visible(actor)

    async def get(self, actor, task_id) -> BindingRecord | None:
        async with self.service_context_factory() as workflow:
            async with workflow._registry.locked(actor, task_id, action="read"):
                conn = workflow._registry.conn
                await self.applications.get(actor, self.config.collaboration_role(actor), task_id,
                                            conn=conn)
                binding = await self.store.get_binding(actor.tenant_id, task_id, conn=conn)
                if binding is not None:
                    await CatalogService(self.config).validate(actor, binding.references)
                return binding

    async def confirm(self, actor, task_id, payload) -> BindingRecord:
        command = BindingCommand.model_validate(payload)
        role = self.config.collaboration_role(actor)
        async with self.service_context_factory() as workflow:
            registry = workflow._registry
            async with registry.locked(actor, task_id, action="read") as record:
                conn = registry.conn
                application = await self.applications.get(actor, role, task_id, conn=conn)
                authorize(actor, role, application, "edit_materials")
                if actor != record.identity:
                    raise AccessDenied("只有实际任务申请人可以确认对象")
                workflow._config(record)
                workflow._check_mode(record)
                snapshot = await workflow._snapshot(record)
                state = snapshot.values
                if (not state or state["revision"] != command.expected_material_revision
                        or await registry.pending(task_id) or snapshot.next or snapshot.interrupts
                        or state["status"] != "awaiting_review"):
                    raise InvalidTransition("材料版本已过期或存在待完成/恢复的材料操作")
                # Bounded ACL I/O precedes the short write transaction. The real task
                # lock remains held; no fixed profile or owner substitution is used.
                await CatalogService(self.config).validate(actor, command)
                async with conn.transaction():
                    # Same P12 ordering: task lock -> request namespace -> application row.
                    # Independent prefix AND hash seed avoid colliding with P12 receipts.
                    key = json.dumps(["precheck-binding-command-v1", actor.tenant_id,
                                      actor.user_id, command.request_id])
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 19))", (key,))
                    application = await self.applications.get(
                        actor, role, task_id, conn=conn, for_update=True)
                    authorize(actor, role, application, "edit_materials")
                    previous = await self.store.receipt(conn, actor, command.request_id)
                    if previous:
                        if (previous["task_id"] != task_id or previous["payload"] !=
                                command.model_dump(mode="json")):
                            raise InvalidTransition("相同 request_id 的任务或完整载荷不同")
                        return BindingRecord.model_validate(previous["result"])
                    current = await self.store.get_binding(actor.tenant_id, task_id, conn=conn)
                    if command.expected_binding_revision != (current.binding_revision if current
                                                             else 0):
                        raise InvalidTransition("对象绑定版本已过期，请重新查看")
                    binding = await self.store.write_binding(conn, actor, task_id, command, current)
                    await self.store.save_receipt(conn, actor, task_id, command, binding)
                    return binding
