"""Execute frozen safety slices against real policy and deterministic query code."""

import json
from pathlib import Path

import pytest
from test_business_query import APPLICANT, NOW, AuthorizedWorkflow, Knowledge

from anlan.business_query.service import BusinessQueryService
from anlan.common.errors import AccessDenied
from anlan.conversation.contracts import BUSINESS_QUERY_INTENTS, ConversationState
from anlan.conversation.policy import decide
from anlan.conversation.service import ConversationService
from anlan.llm.conversation import ConversationContext, ScriptedConversationModel, VisibleMessage

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "evals/business-query-v1/cases.json").read_text(encoding="utf-8"))


def test_frozen_manifest_is_bounded_complete_and_unambiguous():
    assert len(CASES) >= 16
    assert len({c["case_id"] for c in CASES}) == len(CASES)
    assert {"application_status", "application_details", "process_guidance", "safety_knowledge",
            "knowledge_unknown", "no_target", "one_target", "multiple_targets", "unauthorized",
            "cross_tenant", "reviewer_material_write", "mixed_query_write", "quoted", "negation",
            "injection"} <= {c["slice"] for c in CASES}
    for case in CASES:
        assert {"case_id", "slice", "role", "input", "expected_query_type", "expected_outcome",
                "required_evidence_keys", "max_business_writes", "forbidden_markers"} <= case.keys()
        assert 0 < len(case["input"]) <= 500 and case["max_business_writes"] == 0
        assert case["role"] in {"applicant", "safety_manager"}
        assert case["expected_outcome"] in {"ok", "unknown", "selection_required", "error"}
        assert case["forbidden_markers"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
async def test_frozen_case_executes_read_only_policy_and_grounded_gateway(case):
    count = {"one_target": 1, "multiple_targets": 25}.get(case["slice"], 0)
    workflow = AuthorizedWorkflow(count)
    workflow.role = lambda actor: case["role"]
    workflow.constrain = lambda actor, proposal: (
        proposal.model_copy(update={"intent": "casual_chat", "fields": {}})
        if case["role"] == "safety_manager" and proposal.intent == "task_input_candidate"
        else proposal)
    active = None if case["slice"] in {"no_target", "one_target", "multiple_targets"} else "task-1"
    text = case["input"]
    state = ConversationState(conversation_id="c", revision=1,
                              status="active_hot_work" if active else "idle", active_task_id=active)
    proposal = await ScriptedConversationModel().classify(ConversationContext(
        status=state.status, messages=[VisibleMessage(role="user", text=text)]))
    proposal = ConversationService._constrain_proposal(state, text, proposal)
    route = decide(state, proposal)
    assert BUSINESS_QUERY_INTENTS[proposal.intent] == case["expected_query_type"]
    assert route.business_write is False
    knowledge = Knowledge("no_evidence" if case["slice"] == "knowledge_unknown" else "ok")
    service = BusinessQueryService(workflow, clock=lambda: NOW,
                                   knowledge_provider=lambda: knowledge)
    try:
        answer = await service.answer(
            APPLICANT, query_type=route.query_type, question=text, active_task_id=active,
            explicit_task_id=("foreign" if case["slice"] in {"unauthorized", "cross_tenant"}
                              else None))
        assert answer.outcome == case["expected_outcome"]
        output = answer.text
        keys = {fact.key for fact in answer.evidence.facts} if answer.evidence else set()
        assert set(case["required_evidence_keys"]) <= keys
    except AccessDenied:
        assert case["expected_outcome"] == "error"
        output = "申请不存在或当前身份无权访问"
    pending = None
    if proposal.query_write:
        pending = await ConversationService(None, None, workflow)._freeze_query_follow_up(
            APPLICANT, "c", "m", state, proposal)
    assert (pending.intent if pending else None) == case.get("expected_pending_kind")
    assert all(marker not in output for marker in case["forbidden_markers"])
    assert workflow.write_calls == []
