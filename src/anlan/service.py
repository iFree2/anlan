"""Trusted application boundary, scoped to one sequential local CLI process."""

from copy import deepcopy
from uuid import uuid4

from langgraph.types import Command

from anlan.analysis import Analyzer
from anlan.contracts import Application, Identity, Supplement
from anlan.trace import JsonlTrace
from anlan.workflow import build_graph


class AccessDenied(Exception):
    """Same error for missing and unauthorized tasks; no existence disclosure."""


class InvalidTransition(Exception):
    pass


class WorkflowService:
    def __init__(self, analyzer: Analyzer, trace: JsonlTrace | None = None):
        self.trace = trace or JsonlTrace()
        self._graph = build_graph(analyzer, self.trace)
        self._owners: dict[str, tuple[Identity, str]] = {}

    def _config(self, identity: Identity, task_id: str) -> dict:
        record = self._owners.get(task_id)
        if record is None or record[0] != identity:
            raise AccessDenied("任务不存在或当前测试身份无权访问")
        return {"configurable": {"thread_id": record[1]}, "recursion_limit": 8}

    async def start(self, identity: Identity, fields: dict) -> dict:
        application = Application.model_validate(fields)
        task_id, thread_id = str(uuid4()), str(uuid4())
        self._owners[task_id] = (identity, thread_id)
        state = {
            "task_id": task_id, "thread_id": thread_id,
            "session_id": str(uuid4()), "run_id": str(uuid4()),
            "correlation_id": str(uuid4()), "fields": application.model_dump(),
            "revision": 1, "status": "analyzing", "analysis": {}, "trace_warning": None,
        }
        await self._graph.ainvoke(state, self._config(identity, task_id))
        return await self.get(identity, task_id)

    async def get(self, identity: Identity, task_id: str) -> dict:
        snapshot = await self._graph.aget_state(self._config(identity, task_id))
        return deepcopy(snapshot.values)

    async def resume(self, identity: Identity, task_id: str,
                     expected_revision: int, fields: dict) -> dict:
        config = self._config(identity, task_id)
        snapshot = await self._graph.aget_state(config)
        state = snapshot.values
        if (type(expected_revision) is not int or expected_revision != state["revision"]
                or state["status"] != "waiting_input" or not snapshot.next):
            raise InvalidTransition("任务非待补充或回答版本已过期；请先读取当前状态")
        supplement = Supplement.model_validate({"fields": fields})
        await self._graph.ainvoke(Command(resume={
            "fields": supplement.fields, "run_id": str(uuid4()),
        }), config)
        return await self.get(identity, task_id)
