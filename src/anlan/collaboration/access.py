"""Task authorization keeps the real actor separate from the storage owner."""

import asyncio

from anlan.collaboration.contracts import ApplicationRecord
from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied, InvalidTransition


def project_materials(state):
    """Explicit shared allowlist; no private execution IDs, errors, prompts or traces."""
    return {key: state[key] for key in (
        "task_id", "fields", "revision", "status", "analysis_mode") if key in state}


class TaskAccess:
    def __init__(self, config=None):
        self.config = config

    def role(self, actor):
        return self.config.collaboration_role(actor) if self.config else None

    def check_start(self, actor):
        if self.role(actor) == "safety_manager":
            raise AccessDenied("当前身份不能创建材料申请")

    async def application(self, conn, task_id):
        # Older CLI composition may run before collaboration initialization.
        cursor = await conn.execute(
            "SELECT to_regclass('anlan_v2.collaboration_applications') AS relation")
        if (await cursor.fetchone())["relation"] is None:
            return None
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.collaboration_applications WHERE task_id=%s", (task_id,))
        row = await cursor.fetchone()
        return ApplicationRecord.model_validate(row) if row else None

    async def check(self, conn, actor, storage_scope, task_id, action):
        if actor.tenant_id != storage_scope.tenant_id:
            raise AccessDenied("任务不存在或当前身份无权访问")
        app = await self.application(conn, task_id)
        if action == "owner_read":
            if actor != storage_scope:
                raise AccessDenied("任务不存在或当前身份无权访问")
            if app and self.config:
                authorize(actor, self.role(actor), app, "read")
            return
        if app and self.config:
            authorize(actor, self.role(actor), app, action)
        else:
            # No configured collaboration grants: preserve original private access,
            # but persisted freezes still apply to CLI/recovery/old compositions.
            if actor != storage_scope:
                raise AccessDenied("任务不存在或当前身份无权访问")
            if action == "edit_materials":
                self.check_start(actor)
                if app and app.status not in {"draft", "changes_requested"}:
                    raise InvalidTransition("当前申请阶段冻结材料写入")


class GuardedMaterialGraph:
    """Graph writes require the service's active, authorized task-lock context."""

    def __init__(self, graph, registry):
        self._graph, self._registry = graph, registry

    def __getattr__(self, name):
        if name in {"aget_state", "aget_state_history", "get_state", "get_state_history",
                    "get_graph", "aget_graph"}:
            return getattr(self._graph, name)
        raise AccessDenied("请通过授权材料服务执行 Graph")

    async def _check(self, config):
        active = self._registry.material_context
        if not active or active[0] is not asyncio.current_task():
            raise AccessDenied("Graph 写入缺少任务授权锁")
        _, actor, record, action = active
        if (action != "edit_materials" or
                config.get("configurable", {}).get("thread_id") != record.thread_id):
            raise AccessDenied("Graph 写入与当前任务授权不符")
        await self._registry.access.check(
            self._registry.conn, actor, record.identity, record.task_id, "edit_materials")

    async def ainvoke(self, value, config=None, **kwargs):
        await self._check(config or {})
        return await self._graph.ainvoke(value, config, **kwargs)

    async def aupdate_state(self, config, values, **kwargs):
        await self._check(config)
        return await self._graph.aupdate_state(config, values, **kwargs)

    async def astream(self, value, config=None, **kwargs):
        await self._check(config or {})
        async for chunk in self._graph.astream(value, config, **kwargs):
            yield chunk
