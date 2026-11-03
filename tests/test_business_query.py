"""Strict query boundary and deterministic gateway acceptance."""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from anlan.business_query.contracts import EvidenceBundle, EvidenceCitation, QueryText, QueryType
from anlan.business_query.service import BusinessQueryService
from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.interfaces.conversation_runtime import TaskProjection, WorkflowResult

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
APPLICANT = Identity(tenant_id="query-test", user_id="applicant")


class AuthorizedWorkflow:
    def __init__(self, count=0):
        self.count, self.read_calls, self.write_calls = count, [], []
        self.status = "changes_requested"
        self.malformed = False

    def role(self, actor):
        return "applicant"

    async def applications(self, actor):
        return [{"task_id": f"task-{i}", "status": "draft", "version": 1,
                 "private": "PRIVATE-SELECT"} for i in range(self.count)]

    async def read(self, actor, task_id):
        self.read_calls.append((actor, task_id))
        if task_id == "foreign":
            raise AccessDenied("private existence")
        shared = None if self.malformed else {
            "application": {"status": self.status, "version": 2},
            "allowed_actions": ["edit_materials", "resubmit"],
            "private": "PRIVATE-RAW", "events": [{"private": "PRIVATE-EVENT"}],
        }
        return WorkflowResult(projection=TaskProjection(
            task_id=task_id, status="waiting_input", revision=3,
            fields={"work_object_description": "V101管线"},
            missing_fields=["attachment_description"], analysis_mode="offline",
            semantic_status="offline_not_checked", recoverable=True, collaboration=shared))


@pytest.mark.parametrize("query_type", ["application_status", "application_details",
                                       "process_guidance"])
async def test_gateway_uses_only_authorized_projection(query_type):
    workflow = AuthorizedWorkflow()
    answer = await BusinessQueryService(workflow, clock=lambda: NOW).answer(
        APPLICANT, query_type=query_type, question="当前材料？",
        active_task_id="task-1", explicit_task_id=None)
    assert answer.outcome == "ok"
    assert answer.evidence.task_id == "task-1"
    assert answer.evidence.material_revision == 3 and answer.evidence.application_version == 2
    assert "task-1" in answer.text and NOW.isoformat() in answer.text
    assert "PRIVATE" not in answer.model_dump_json()
    assert workflow.read_calls == [(APPLICANT, "task-1")] and not workflow.write_calls
    if query_type == "application_status":
        assert "要求补充" in answer.text and "附件说明" in answer.text
    if query_type == "application_details":
        assert "V101管线" in answer.text


@pytest.mark.parametrize("count,outcome", [(0, "unknown"), (1, "selection_required"),
                                          (25, "selection_required")])
async def test_target_selection_is_bounded_and_never_binds(count, outcome):
    workflow = AuthorizedWorkflow(count)
    answer = await BusinessQueryService(workflow).answer(
        APPLICANT, query_type="application_status", question="状态？",
        active_task_id=None, explicit_task_id=None)
    assert answer.outcome == outcome and answer.evidence is None
    assert len(answer.candidate_tasks) == min(count, 20)
    assert "PRIVATE" not in answer.model_dump_json()
    assert not workflow.read_calls and not workflow.write_calls


async def test_explicit_target_wins_and_denial_remains_uniform():
    workflow = AuthorizedWorkflow()
    service = BusinessQueryService(workflow)
    answer = await service.answer(APPLICANT, query_type="application_status", question="状态？",
                                  active_task_id="task-1", explicit_task_id="task-2")
    assert answer.evidence.task_id == "task-2"
    with pytest.raises(AccessDenied):
        await service.answer(APPLICANT, query_type="application_status", question="状态？",
                             active_task_id="task-1", explicit_task_id="foreign")
    workflow.malformed = True
    answer = await service.answer(APPLICANT, query_type="application_status", question="状态？",
                                  active_task_id="task-1", explicit_task_id=None)
    assert answer.outcome == "error" and "PRIVATE" not in answer.text


async def test_review_completed_never_means_permission():
    workflow = AuthorizedWorkflow()
    workflow.status = "review_completed"
    answer = await BusinessQueryService(workflow).answer(
        APPLICANT, query_type="process_guidance", question="下一步？",
        active_task_id="task-1", explicit_task_id=None)
    assert "不代表作业批准或开工授权" in answer.text


def test_query_contracts_reject_unknown_unbounded_and_partial_evidence():
    for value in ("write", "", 1):
        with pytest.raises(ValidationError):
            TypeAdapter(QueryType).validate_python(value)
    with pytest.raises(ValidationError):
        TypeAdapter(QueryText).validate_python("x" * 501)
    with pytest.raises(ValidationError):
        EvidenceCitation.model_validate({"chunk_id": "c"})
    for revision in (0, -1, None):
        with pytest.raises(ValidationError):
            EvidenceBundle(query_type="application_status", task_id="t",
                           material_revision=revision, application_version=1, observed_at=NOW)
    with pytest.raises(ValidationError):
        EvidenceBundle(query_type="safety_knowledge", observed_at=NOW, private_messages=[])
