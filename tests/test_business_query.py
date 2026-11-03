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


async def test_status_answer_names_the_current_handler_from_state_rules():
    workflow = AuthorizedWorkflow()
    workflow.status = "under_review"
    answer = await BusinessQueryService(workflow).answer(
        APPLICANT, query_type="application_status", question="轮到谁？",
        active_task_id="task-1", explicit_task_id=None)
    assert "指定安全审核人员" in answer.text


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


async def test_replay_reauthorizes_explicit_target_and_knowledge_citations():
    workflow = AuthorizedWorkflow()
    service = BusinessQueryService(workflow, clock=lambda: NOW)
    answer = await service.answer(APPLICANT, query_type="application_status", question="状态？",
                                  active_task_id=None, explicit_task_id="task-1")
    reference = service.replay_reference(answer, "application_status")
    assert "fields" not in str(reference) and "quote" not in str(reference)

    async def denied(actor, task_id):
        raise AccessDenied("revoked")

    workflow.read = denied
    with pytest.raises(AccessDenied):
        await service.validate_replay(APPLICANT, reference, "状态？")
    knowledge = Knowledge()
    service = BusinessQueryService(workflow, clock=lambda: NOW,
                                   knowledge_provider=lambda: knowledge)
    answer = await service.answer(APPLICANT, query_type="safety_knowledge", question="动火？",
                                  active_task_id=None, explicit_task_id=None)
    reference = service.replay_reference(answer, "safety_knowledge")
    await service.validate_replay(APPLICANT, reference, "动火？")
    knowledge.mode = "revoked"
    with pytest.raises(AccessDenied):
        await service.validate_replay(APPLICANT, reference, "动火？")


async def test_query_is_audited_before_answer_and_audit_failure_is_not_ignored():
    class Audit:
        rows = []
        fail = False

        async def record(self, actor, role, receipt):
            if self.fail:
                raise RuntimeError("PRIVATE-AUDIT")
            self.rows.append((actor, role, receipt))

    audit = Audit()
    service = BusinessQueryService(AuthorizedWorkflow(), audit=audit)
    await service.answer(APPLICANT, query_type="application_status", question="PRIVATE-QUESTION",
                         active_task_id="task-1", explicit_task_id=None, source_message_id="msg-1")
    assert len(audit.rows) == 1
    assert audit.rows[0][2].source_message_id == "msg-1"
    assert "PRIVATE" not in audit.rows[0][2].model_dump_json()
    audit.fail = True
    with pytest.raises(RuntimeError):
        await service.answer(APPLICANT, query_type="application_status", question="状态？",
                             active_task_id="task-1", explicit_task_id=None,
                             source_message_id="msg-2")


@pytest.mark.parametrize("unstable", [False, True])
async def test_version_change_retries_once_then_refuses_unstable_snapshot(unstable):
    workflow = AuthorizedWorkflow()
    original_read = workflow.read

    async def read(actor, target):
        result = await original_read(actor, target)
        return result.model_copy(update={"projection": result.projection.model_copy(
            update={"revision": 2 + len(workflow.read_calls)})})

    async def versions(actor, target):
        return (3 + len(workflow.read_calls) if unstable else 4, 2)

    workflow.read, workflow.query_versions = read, versions
    answer = await BusinessQueryService(workflow).answer(
        APPLICANT, query_type="application_status", question="当前状态？",
        active_task_id="task-1", explicit_task_id=None)
    assert len(workflow.read_calls) == 2
    if unstable:
        assert answer.outcome == "error" and "刷新" in answer.text
    else:
        assert answer.evidence.material_revision == 4


async def test_long_details_and_twenty_uuid_summaries_fit_answer_contract():
    from uuid import uuid4

    workflow = AuthorizedWorkflow(20)

    async def applications(actor):
        return [{"task_id": str(uuid4()), "status": "draft", "version": 1} for _ in range(20)]

    workflow.applications = applications
    selection = await BusinessQueryService(workflow).answer(
        APPLICANT, query_type="application_status", question="状态？",
        active_task_id=None, explicit_task_id=None)
    assert selection.outcome == "selection_required" and len(selection.text) > 500
    original = workflow.read

    async def read(actor, target):
        result = await original(actor, target)
        return result.model_copy(update={"projection": result.projection.model_copy(
            update={"fields": {"work_object_description": "管" * 2000}})})

    workflow.read = read
    details = await BusinessQueryService(workflow).answer(
        APPLICANT, query_type="application_details", question="作业对象是什么？",
        active_task_id="task-1", explicit_task_id=None)
    assert details.outcome == "ok" and "管" * 2000 in details.text


async def test_composer_exception_returns_safe_fixed_application_fallback():
    service = BusinessQueryService(AuthorizedWorkflow())

    def broken(bundle):
        raise RuntimeError("PRIVATE-TEMPLATE")

    service._compose_application = broken
    answer = await service.answer(APPLICANT, query_type="application_status", question="状态？",
                                  active_task_id="task-1", explicit_task_id=None)
    assert answer.outcome == "error" and "PRIVATE" not in answer.text


async def test_four_maximum_fields_fit_private_message_byte_budget_with_provenance():
    from anlan.workflows.material_contracts import LABELS

    workflow = AuthorizedWorkflow()
    original = workflow.read

    async def read(actor, target):
        result = await original(actor, target)
        return result.model_copy(update={"projection": result.projection.model_copy(
            update={"fields": {key: "材" * 2000 for key in LABELS}})})

    workflow.read = read
    answer = await BusinessQueryService(workflow, clock=lambda: NOW).answer(
        APPLICANT, query_type="application_details", question="详情？",
        active_task_id="task-1", explicit_task_id=None)
    assert answer.outcome == "ok"
    assert len(answer.text.encode("utf-8")) <= 7600
    assert "已截断" in answer.text and "answer_truncated" in answer.evidence.limitations
    assert "材料版本 3" in answer.text and "申请版本 2" in answer.text
    assert NOW.isoformat() in answer.text


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
