"""经授权的任务入口：命令可持久化，恢复路径显式。"""

import json
from copy import deepcopy
from typing import Callable
from uuid import NAMESPACE_URL, uuid4, uuid5

from langgraph.types import Command

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity
from anlan.infrastructure.trace import JsonlTrace
from anlan.workflows.material_analysis import Analyzer
from anlan.workflows.material_contracts import Application, Supplement
from anlan.workflows.materials import build_graph
from anlan.workflows.registry import (
    CONTRACT_VERSION,
    MemoryRegistry,
    Operation,
    Registry,
    TaskRecord,
)

__all__ = ["AccessDenied", "InvalidTransition", "WorkflowService"]


def start_task_id(identity: Identity, request_id: str) -> str:
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 100:
        raise InvalidTransition("start request_id无效")
    return str(uuid5(NAMESPACE_URL, json.dumps(
        ["anlan-material-start-v1", identity.tenant_id, identity.user_id, request_id])))


class WorkflowService:
    def __init__(self, analyzer: Analyzer, trace: JsonlTrace | None = None, *,
                 registry: Registry | None = None, checkpointer=None, mode: str = "offline"):
        self.trace = trace or JsonlTrace()
        self._graph = build_graph(analyzer, self.trace, checkpointer)
        self._registry = registry if registry is not None else MemoryRegistry()
        self.mode = mode

    @staticmethod
    def _config(record: TaskRecord) -> dict:
        if record.contract_version != CONTRACT_VERSION:
            raise InvalidTransition("任务状态版本不兼容，需要迁移")
        return {"configurable": {"thread_id": record.thread_id}, "recursion_limit": 8}

    def _check_mode(self, record: TaskRecord) -> None:
        if record.mode != self.mode:
            raise InvalidTransition("任务分析模式不同，续接时请使用创建任务时的 mode")

    async def start(self, identity: Identity, fields: dict, *,
                    on_created: Callable[[str], None] | None = None,
                    request_id: str | None = None) -> dict:
        application = Application.model_validate(fields)
        task_id, thread_id = str(uuid4()), str(uuid4())
        if request_id is not None:
            task_id = start_task_id(identity, request_id)
        state = {
            "task_id": task_id, "thread_id": thread_id,
            "session_id": str(uuid4()), "run_id": str(uuid4()),
            "correlation_id": str(uuid4()), "fields": application.model_dump(),
            "revision": 1, "status": "analyzing", "analysis": {}, "trace_warning": None,
            "analysis_mode": self.mode,
        }
        record = TaskRecord(task_id, thread_id, identity, self.mode, state)
        if request_id is None:
            await self._registry.create(record)
        else:
            await self._registry.create(record, idempotent=True)
        if on_created is not None:
            on_created(task_id)
        async with self._registry.locked(identity, task_id) as record:
            self._config(record)
            self._check_mode(record)
            if record.initial_state["fields"] != state["fields"]:
                raise InvalidTransition("相同start request_id的初始材料不同")
            previous = await self._registry.operation(task_id, "start")
            if previous is not None:
                if previous.result is not None:
                    return deepcopy(previous.result)
                raise InvalidTransition("创建尚未完成；请执行recover")
            initial = record.initial_state
            operation = Operation("start", initial["run_id"], "start", 0, initial["fields"])
            await self._registry.reserve(task_id, operation)
            return await self._execute(record, operation)

    async def _snapshot(self, record: TaskRecord):
        return await self._graph.aget_state(self._config(record))

    async def get(self, identity: Identity, task_id: str) -> dict:
        async with self._registry.locked(identity, task_id) as record:
            snapshot = await self._snapshot(record)
            if not snapshot.values:
                raise InvalidTransition("任务尚未写入 checkpoint；请执行 recover")
            return deepcopy(snapshot.values)

    async def resume(self, identity: Identity, task_id: str, expected_revision: int,
                     fields: dict, *, request_id: str | None = None) -> dict:
        return await self._submit(identity, task_id, expected_revision, fields,
                                  request_id=request_id, kind="resume")

    async def revise(self, identity: Identity, task_id: str, expected_revision: int,
                     fields: dict, *, request_id: str | None = None) -> dict:
        """Explicit new analysis revision for a completed material task; never approval."""
        return await self._submit(identity, task_id, expected_revision, fields,
                                  request_id=request_id, kind="revise")

    async def _submit(self, identity, task_id, expected_revision, fields, *, request_id, kind):
        async with self._registry.locked(identity, task_id) as record:
            self._check_mode(record)
            self._config(record)  # 在返回缓存结果之前，先校验状态契约版本。
            supplement = Supplement.model_validate({"fields": fields})
            request_id = request_id if request_id is not None else str(uuid4())
            if (not isinstance(request_id, str) or not request_id.strip()
                    or len(request_id) > 100 or request_id == "start"):
                raise InvalidTransition("request_id 无效或使用了保留值")
            if type(expected_revision) is not int or expected_revision < 1:
                raise InvalidTransition("回答版本无效")
            previous = await self._registry.operation(task_id, request_id)
            if previous is not None:
                if (previous.kind != kind or previous.fields != supplement.fields
                        or previous.expected_revision != expected_revision):
                    raise InvalidTransition("相同 request_id 的载荷不同")
                if previous.result is not None:
                    return deepcopy(previous.result)
                raise InvalidTransition("提交尚未完成；请执行 recover")
            if await self._registry.pending(task_id):
                raise InvalidTransition("存在未完成提交；请执行 recover")
            snapshot = await self._snapshot(record)
            state = snapshot.values
            allowed = bool(state) and (
                state["status"] == "waiting_input" and bool(snapshot.interrupts)
                if kind == "resume" else
                state["status"] == "awaiting_review"
                and not snapshot.interrupts and not snapshot.next
            )
            if not allowed or expected_revision != state["revision"]:
                raise InvalidTransition("任务状态不允许该操作或版本已过期；请先读取当前状态")
            operation = Operation(request_id, str(uuid4()), kind, expected_revision,
                                  supplement.fields)
            await self._registry.reserve(task_id, operation)
            return await self._execute(record, operation)

    async def _execute(self, record: TaskRecord, operation: Operation) -> dict:
        snapshot = await self._snapshot(record)
        state = snapshot.values
        config = self._config(record)
        if not state:
            if operation.kind != "start":
                raise InvalidTransition("checkpoint 缺失，需要人工排查")
            await self._graph.ainvoke(record.initial_state, config, durability="sync")
        elif state["run_id"] == operation.run_id:
            # 材料已合并后发生的崩溃，不能再次合并字段或重复递增 revision。
            if (state["status"] == "analyzing" or
                    (state["status"] == "waiting_input" and not snapshot.interrupts
                     and snapshot.next)):
                await self._graph.ainvoke(None, config, durability="sync")
        elif (operation.kind == "resume" and state["revision"] == operation.expected_revision
              and state["status"] == "waiting_input"):
            await self._graph.ainvoke(Command(resume={
                "fields": operation.fields, "run_id": operation.run_id,
            }), config, durability="sync")
        elif (operation.kind == "revise" and state["revision"] == operation.expected_revision
              and state["status"] == "awaiting_review" and not snapshot.interrupts
              and not snapshot.next):
            fields = Application.model_validate({**state["fields"], **operation.fields})
            await self._graph.ainvoke({
                **state, "fields": fields.model_dump(), "revision": state["revision"] + 1,
                "run_id": operation.run_id, "status": "analyzing", "analysis": {},
                "trace_warning": None,
            }, config, durability="sync")
        else:
            raise InvalidTransition("提交记录与 checkpoint 不一致，需要人工排查")
        result = deepcopy((await self._snapshot(record)).values)
        if result["status"] not in ("waiting_input", "awaiting_review"):
            raise InvalidTransition("执行尚未到可交付状态；请执行 recover")
        await self._registry.complete(record.task_id, operation.request_id, result)
        return result

    async def recover(self, identity: Identity, task_id: str) -> dict:
        async with self._registry.locked(identity, task_id) as record:
            self._check_mode(record)
            operation = await self._registry.pending(task_id)
            if operation is None:
                # 也覆盖“已写入归属、但尚未 reserve”这一小段崩溃窗口。
                snapshot = await self._snapshot(record)
                if snapshot.values:
                    return deepcopy(snapshot.values)
                operation = Operation("start", record.initial_state["run_id"], "start", 0,
                                      record.initial_state["fields"])
                await self._registry.reserve(task_id, operation)
            return await self._execute(record, operation)

    async def history(self, identity: Identity, task_id: str) -> list[dict]:
        async with self._registry.locked(identity, task_id):
            return await self._registry.history(task_id)
