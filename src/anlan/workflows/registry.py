"""Task ownership and submitted commands; current material stays in Graph checkpoints."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import AsyncContextManager, Protocol

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity

CONTRACT_VERSION = "material-state-v1"


@dataclass
class TaskRecord:
    task_id: str
    thread_id: str
    identity: Identity
    mode: str
    initial_state: dict
    contract_version: str = CONTRACT_VERSION


@dataclass
class Operation:
    request_id: str
    run_id: str
    kind: str
    expected_revision: int
    fields: dict
    result: dict | None = None


class Registry(Protocol):
    async def create(self, record: TaskRecord) -> None: ...
    def locked(self, identity: Identity, task_id: str) -> AsyncContextManager[TaskRecord]: ...
    async def operation(self, task_id: str, request_id: str) -> Operation | None: ...
    async def pending(self, task_id: str) -> Operation | None: ...
    async def reserve(self, task_id: str, operation: Operation) -> None: ...
    async def complete(self, task_id: str, request_id: str, result: dict) -> None: ...
    async def history(self, task_id: str) -> list[dict]: ...


class MemoryRegistry:
    def __init__(self):
        self.records: dict[str, TaskRecord] = {}
        self.operations: dict[tuple[str, str], Operation] = {}
        self.lock = asyncio.Lock()

    async def create(self, record: TaskRecord) -> None:
        self.records[record.task_id] = deepcopy(record)

    @asynccontextmanager
    async def locked(self, identity: Identity, task_id: str):
        async with self.lock:
            record = self.records.get(task_id)
            if record is None or record.identity != identity:
                raise AccessDenied("任务不存在或当前测试身份无权访问")
            yield deepcopy(record)

    async def operation(self, task_id: str, request_id: str) -> Operation | None:
        return deepcopy(self.operations.get((task_id, request_id)))

    async def pending(self, task_id: str) -> Operation | None:
        return next((deepcopy(op) for (task, _), op in self.operations.items()
                     if task == task_id and op.result is None), None)

    async def reserve(self, task_id: str, operation: Operation) -> None:
        self.operations[(task_id, operation.request_id)] = deepcopy(operation)

    async def complete(self, task_id: str, request_id: str, result: dict) -> None:
        self.operations[(task_id, request_id)].result = deepcopy(result)

    async def history(self, task_id: str) -> list[dict]:
        return [{"request_id": op.request_id, "run_id": op.run_id, "kind": op.kind,
                 "expected_revision": op.expected_revision,
                 "status": "pending" if op.result is None else "completed"}
                for (task, _), op in self.operations.items() if task == task_id]
