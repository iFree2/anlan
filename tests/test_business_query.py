"""Strict query boundary and deterministic gateway acceptance."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from anlan.business_query.contracts import (
    EvidenceBundle,
    EvidenceCitation,
    QueryAnswer,
    QueryText,
    QueryType,
)
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


class Knowledge:
    clock = staticmethod(lambda: NOW)

    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []

    async def search(self, actor, parameters):
        self.calls.append((actor, parameters))
        if self.mode == "unavailable":
            raise RuntimeError("PRIVATE-CREDENTIAL")
        if self.mode == "timeout":
            raise TimeoutError()
        citations = [{
            "doc_id": "doc-1", "chunk_id": "chunk-1", "version": 1, "title": "合成动火规程",
            "source": "synthetic/policy", "quote": "动火前应检测可燃气体。",
            "content_hash": "a" * 64, "document_hash": "b" * 64,
            "valid_from": (NOW - timedelta(days=1)).isoformat(),
            "valid_until": (NOW + timedelta(days=1)).isoformat(),
            "rank_score": 0.9,
        }]
        if self.mode in {"no_evidence", "revoked"}:
            citations = []
        elif self.mode == "expired":
            citations[0]["valid_until"] = NOW.isoformat()
        elif self.mode == "missing_hash":
            del citations[0]["content_hash"]
        return {"outcome": "ok" if citations else "unknown", "reason": None,
                "queried_at": NOW.isoformat(), "citations": citations}


@pytest.mark.parametrize("mode", ["ok", "no_evidence", "revoked", "unavailable", "timeout",
                                  "expired", "missing_hash"])
async def test_safety_knowledge_is_only_a_current_authorized_quote(mode):
    knowledge = Knowledge(mode)
    service = BusinessQueryService(AuthorizedWorkflow(), clock=lambda: NOW,
                                   knowledge_provider=lambda: knowledge)
    answer = await service.answer(APPLICANT, query_type="safety_knowledge",
                                  question="为什么气体检测？",
                                  active_task_id=None, explicit_task_id=None)
    assert len(knowledge.calls) == 1
    assert "PRIVATE" not in answer.text and "受限空间" not in answer.text
    if mode == "ok":
        assert answer.outcome == "ok" and answer.evidence.task_id is None
        assert answer.evidence.citations[0].chunk_id == "chunk-1"
        assert "可燃气体" in answer.text and "doc-1/chunk-1" in answer.text
        assert NOW.isoformat() in answer.text
    else:
        assert answer.outcome in {"unknown", "error"}
        assert "可燃气体" not in answer.text


async def test_valid_long_knowledge_quote_is_not_misreported_as_unavailable():
    knowledge = Knowledge()
    search = knowledge.search

    async def long_search(actor, parameters):
        result = await search(actor, parameters)
        result["citations"][0]["quote"] = "合成安全依据。" * 100
        return result

    knowledge.search = long_search
    answer = await BusinessQueryService(AuthorizedWorkflow(), clock=lambda: NOW,
                                       knowledge_provider=lambda: knowledge).answer(
        APPLICANT, query_type="safety_knowledge", question="动火？",
        active_task_id=None, explicit_task_id=None)
    assert answer.outcome == "ok" and len(answer.text) > 500


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


def test_successful_knowledge_envelope_requires_citations():
    with pytest.raises(ValidationError):
        QueryAnswer(text="无引用的安全结论", outcome="ok", evidence=EvidenceBundle(
            query_type="safety_knowledge", observed_at=NOW))
