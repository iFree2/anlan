"""Controlled adapter from conversation decisions to the material workflow."""

import hashlib
from typing import Literal

from pydantic import Field

from anlan.common.errors import InvalidTransition
from anlan.common.models import NonEmpty, StrictModel
from anlan.workflows.material_contracts import Application, FieldName, Supplement, Text

TaskStatus = Literal["analyzing", "waiting_input", "awaiting_review"]
SemanticStatus = Literal["offline_not_checked", "checked", "failed"]


class TaskProjection(StrictModel):
    task_id: NonEmpty
    status: TaskStatus
    revision: int = Field(strict=True, ge=1)
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    missing_fields: list[FieldName] = Field(default_factory=list, max_length=4)
    issue_questions: list[NonEmpty] = Field(default_factory=list, max_length=4)
    analysis_mode: NonEmpty
    semantic_status: SemanticStatus
    recoverable: bool
    event_count: int = Field(default=0, strict=True, ge=0, le=10000)
    review_count: int = Field(default=0, strict=True, ge=0, le=10000)
    stale_review_warning: bool = False


class WorkflowResult(StrictModel):
    projection: TaskProjection


def _request_id(conversation_id: str, message_id: str, action: str) -> str:
    value = f"conversation:{conversation_id}:{message_id}:{action}"
    if len(value) <= 100:
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"conversation:{digest}:{action}"


def _count(state: dict, singular: str, plural: str) -> int:
    explicit = state.get(f"{singular}_count")
    if type(explicit) is int:
        return explicit
    values = state.get(plural)
    return len(values) if isinstance(values, list) else 0


def _project(state: dict) -> TaskProjection:
    application = Application.model_validate(state.get("fields", {}))
    fields = application.model_dump()
    analysis = state.get("analysis") if isinstance(state.get("analysis"), dict) else {}
    issues = analysis.get("issues") if isinstance(analysis.get("issues"), list) else []
    questions = [
        issue["question"]
        for issue in issues[:4]
        if isinstance(issue, dict) and isinstance(issue.get("question"), str)
    ]
    return TaskProjection(
        task_id=state["task_id"],
        status=state["status"],
        revision=state["revision"],
        fields={name: value for name, value in fields.items() if value},
        missing_fields=[name for name, value in fields.items() if not value],
        issue_questions=questions,
        analysis_mode=state["analysis_mode"],
        semantic_status=analysis.get("semantic_status", "failed"),
        recoverable=state["status"] in {"analyzing", "waiting_input"},
        event_count=_count(state, "event", "events"),
        review_count=_count(state, "review", "reviews"),
        stale_review_warning=state.get("stale_review_warning") is True,
    )


class WorkflowAdapter:
    """The sole conversation-layer boundary allowed to write material workflows."""

    def __init__(self, service_context_factory):
        self._service_context_factory = service_context_factory

    async def start(
        self, identity, conversation_id: str, message_id: str, fields: dict
    ) -> WorkflowResult:
        application = Application.model_validate(fields)
        async with self._service_context_factory() as service:
            state = await service.start(
                identity,
                application.model_dump(),
                request_id=_request_id(conversation_id, message_id, "start"),
            )
        return WorkflowResult(projection=_project(state))

    async def submit(
        self,
        identity,
        conversation_id: str,
        message_id: str,
        task_id: str,
        expected_revision: int,
        fields: dict,
        status: str,
    ) -> WorkflowResult:
        supplement = Supplement.model_validate({"fields": fields})
        async with self._service_context_factory() as service:
            current = await service.get(identity, task_id)
            if current.get("status") != status:
                raise InvalidTransition("任务状态已变化；请先读取最新状态")
            if current["status"] == "waiting_input":
                action = "resume"
                method = service.resume
            elif current["status"] == "awaiting_review":
                action = "revise"
                method = service.revise
            else:
                raise InvalidTransition("任务状态不允许提交材料")
            state = await method(
                identity,
                task_id,
                expected_revision,
                supplement.fields,
                request_id=_request_id(conversation_id, message_id, action),
            )
        return WorkflowResult(projection=_project(state))

    async def recover(self, identity, task_id: str) -> WorkflowResult:
        async with self._service_context_factory() as service:
            state = await service.recover(identity, task_id)
        return WorkflowResult(projection=_project(state))

    async def read(self, identity, task_id: str) -> WorkflowResult:
        async with self._service_context_factory() as service:
            state = await service.get(identity, task_id)
        return WorkflowResult(projection=_project(state))
