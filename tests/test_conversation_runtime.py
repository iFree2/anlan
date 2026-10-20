from contextlib import asynccontextmanager

import pytest
from test_events import OWNER

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.interfaces.conversation_runtime import WorkflowAdapter


def waiting_task(**updates):
    value = {
        "task_id": "task-1",
        "status": "waiting_input",
        "revision": 1,
        "fields": {
            "work_location_description": "",
            "work_object_description": "V101 管线补焊",
            "work_method_description": "",
            "attachment_description": "",
        },
        "analysis_mode": "offline",
        "analysis": {
            "semantic_status": "offline_not_checked",
            "issues": [
                {
                    "field": "work_location_description",
                    "kind": "missing",
                    "quote": "",
                    "reason": "字段为空",
                    "question": "请补充具体作业位置。",
                    "source": "rule",
                }
            ],
        },
    }
    value.update(updates)
    return value


class FakeMaterialService:
    def __init__(self, state=None):
        self.state = state or waiting_task()
        self.start_calls = []
        self.get_calls = []
        self.resume_calls = []
        self.revise_calls = []
        self.recover_calls = []
        self.error = None

    async def start(self, identity, fields, *, request_id):
        self.start_calls.append((identity, fields, request_id))
        if self.error:
            raise self.error
        return self.state

    async def get(self, identity, task_id):
        self.get_calls.append((identity, task_id))
        if self.error:
            raise self.error
        return self.state

    async def resume(self, identity, task_id, revision, fields, *, request_id):
        self.resume_calls.append((identity, task_id, revision, fields, request_id))
        if self.error:
            raise self.error
        return self.state | {"revision": revision + 1}

    async def revise(self, identity, task_id, revision, fields, *, request_id):
        self.revise_calls.append((identity, task_id, revision, fields, request_id))
        if self.error:
            raise self.error
        return self.state | {"revision": revision + 1}

    async def recover(self, identity, task_id):
        self.recover_calls.append((identity, task_id))
        if self.error:
            raise self.error
        return self.state


@asynccontextmanager
async def fake_context(material):
    yield material


def adapter(material):
    return WorkflowAdapter(lambda: fake_context(material))


@pytest.mark.asyncio
async def test_start_maps_confirmed_fields_and_uses_message_scoped_request_id():
    material = FakeMaterialService()
    result = await adapter(material).start(
        OWNER,
        "conv-1",
        "message-1",
        {"work_object_description": "V101 管线补焊"},
    )
    assert material.start_calls == [
        (
            OWNER,
            {
                "work_location_description": "",
                "work_object_description": "V101 管线补焊",
                "work_method_description": "",
                "attachment_description": "",
            },
            "conversation:conv-1:message-1:start",
        )
    ]
    assert result.projection.status == "waiting_input"
    assert result.projection.missing_fields == [
        "work_location_description",
        "work_method_description",
        "attachment_description",
    ]


@pytest.mark.asyncio
async def test_submit_reads_fresh_status_and_resumes_only_waiting_input():
    material = FakeMaterialService()
    result = await adapter(material).submit(
        OWNER,
        "conv-1",
        "message-2",
        "task-1",
        1,
        {"work_location_description": "一号罐区"},
        "waiting_input",
    )
    assert material.get_calls == [(OWNER, "task-1")]
    assert material.resume_calls == [
        (
            OWNER,
            "task-1",
            1,
            {"work_location_description": "一号罐区"},
            "conversation:conv-1:message-2:resume",
        )
    ]
    assert material.revise_calls == []
    assert result.projection.revision == 2


@pytest.mark.asyncio
async def test_submit_revises_only_awaiting_review():
    material = FakeMaterialService(
        waiting_task(status="awaiting_review", fields=waiting_task()["fields"] | {
            "work_location_description": "一号罐区",
            "work_method_description": "手工补焊",
            "attachment_description": "未提供附件",
        })
    )
    await adapter(material).submit(
        OWNER,
        "conv-1",
        "message-3",
        "task-1",
        1,
        {"work_method_description": "氩弧焊"},
        "awaiting_review",
    )
    assert material.resume_calls == []
    assert material.revise_calls[0][-1] == "conversation:conv-1:message-3:revise"


@pytest.mark.asyncio
async def test_submit_rejects_stale_status_and_propagates_stale_revision():
    material = FakeMaterialService()
    with pytest.raises(InvalidTransition, match="状态"):
        await adapter(material).submit(
            OWNER, "conv-1", "message-4", "task-1", 1, {"attachment_description": "无"},
            "awaiting_review",
        )
    assert material.resume_calls == material.revise_calls == []

    material.error = InvalidTransition("任务状态不允许该操作或版本已过期")
    with pytest.raises(InvalidTransition, match="版本"):
        await adapter(material).submit(
            OWNER, "conv-1", "message-5", "task-1", 1, {"attachment_description": "无"},
            "waiting_input",
        )


@pytest.mark.asyncio
async def test_recover_and_read_use_only_material_service_reads():
    material = FakeMaterialService()
    recovered = await adapter(material).recover(OWNER, "task-1")
    read = await adapter(material).read(OWNER, "task-1")
    assert recovered.projection.task_id == read.projection.task_id == "task-1"
    assert material.recover_calls == [(OWNER, "task-1")]
    assert material.get_calls == [(OWNER, "task-1")]


@pytest.mark.asyncio
async def test_task_not_found_or_forbidden_is_not_hidden_by_projection():
    material = FakeMaterialService()
    material.error = AccessDenied("任务不存在或无权访问")
    with pytest.raises(AccessDenied):
        await adapter(material).read(OWNER, "missing")


@pytest.mark.asyncio
async def test_projection_is_bounded_and_summarizes_task_state():
    state = waiting_task(
        event_count=3,
        review_count=2,
        stale_review_warning=True,
        raw_model_response="must-not-escape",
        credentials="must-not-escape",
    )
    projection = (await adapter(FakeMaterialService(state)).read(OWNER, "task-1")).projection
    assert projection.fields == {"work_object_description": "V101 管线补焊"}
    assert projection.issue_questions == ["请补充具体作业位置。"]
    assert projection.analysis_mode == "offline"
    assert projection.semantic_status == "offline_not_checked"
    assert projection.recoverable is True
    assert projection.event_count == 3 and projection.review_count == 2
    assert projection.stale_review_warning is True
    dumped = projection.model_dump()
    assert "raw_model_response" not in dumped and "credentials" not in dumped
