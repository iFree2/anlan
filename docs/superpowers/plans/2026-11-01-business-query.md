# Grounded Business Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add grounded, read-only conversational answers for application status, application details, process guidance, and cited hot-work safety knowledge without exposing private messages or mutating business state.

**Architecture:** Extend the existing bounded intent classifier with four query intents, but keep execution deterministic in a new `anlan.business_query` package. A read-only gateway resolves an authorized target, reads the current shared projection, creates a versioned evidence bundle, and uses deterministic composition; knowledge answers reuse the existing tenant-scoped knowledge tool and must retain citations. Conversation orchestration stores the answer only in the caller's private thread, while a separate PostgreSQL audit receipt records bounded metadata rather than question text or evidence content.

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI, PostgreSQL/psycopg 3, LangGraph checkpoint state, pytest/pytest-asyncio, Ruff.

---

## Execution Preconditions

- Execute this plan in a **new Codex chat**, not in the design chat.
- At the start of that chat, read:
  - `docs/superpowers/specs/2026-11-01-business-query-design.md`
  - `docs/superpowers/plans/2026-11-01-business-query.md`
- Use `superpowers:using-git-worktrees` before editing because the source workspace contains unrelated user changes. Create an isolated branch/worktree with the `codex/` prefix and never copy, reset, or commit unrelated changes.
- Use `superpowers:test-driven-development` for every task. Each test must fail for the intended missing behavior before implementation is written.
- Do not create or publish a full `business-query` Skill in this implementation. The stable Python contracts are the future Skill boundary.
- Do not call a live model, deploy, rotate credentials, or change cloud resources. All implementation and acceptance work is local and uses scripted/fake model paths plus the authorized test PostgreSQL database.

## File and Responsibility Map

### Create

- `src/anlan/business_query/__init__.py` — public exports for the query package.
- `src/anlan/business_query/contracts.py` — query types, evidence bundle, citations, answer envelope, and mixed-query follow-up contracts.
- `src/anlan/business_query/service.py` — target resolution, authorization-preserving reads, deterministic evidence creation, process guidance, and answer composition.
- `src/anlan/infrastructure/business_queries.py` — bounded PostgreSQL query-audit persistence.
- `src/anlan/sql/021_business_queries.sql` — additive audit table and migration receipt.
- `tests/test_business_query.py` — pure query-service and deterministic-answer tests.
- `tests/test_business_query_audit.py` — real PostgreSQL audit, idempotency, and isolation tests.
- `tests/test_business_query_evaluation.py` — frozen evaluation-set checks.
- `evals/business-query-v1/README.md` — evaluation purpose, slices, and pass rules.
- `evals/business-query-v1/cases.json` — status, detail, process, knowledge, ambiguity, mixed-intent, isolation, and injection cases.

### Modify

- `src/anlan/conversation/contracts.py` — add four bounded query intents and optional secondary write candidate.
- `src/anlan/conversation/policy.py` — add the read-only query route and prove it never carries `business_write=True`.
- `src/anlan/conversation/service.py` — invoke the query service, persist private answers, and freeze optional follow-up writes separately.
- `src/anlan/llm/conversation.py` — classify bounded query intents in scripted/live modes without allowing the responder to invent facts.
- `src/anlan/interfaces/collaboration_conversation.py` — expose only authorized application summaries and keep reviewer material writes forbidden.
- `src/anlan/interfaces/api.py` — compose and initialize the query service and audit store.
- `src/anlan/infrastructure/postgres.py` — initialize the additive audit migration through the standard database path.
- `tests/test_conversation_policy.py` — prove query routing is read-only in every conversation state.
- `tests/test_conversation_model.py` — scripted/live query classification and host target constraints.
- `tests/test_conversation_service.py` — private answer integration, failure behavior, and mixed-query confirmation.
- `tests/test_collaboration_conversation.py` — two-role isolation and current shared projection answers.
- `tests/test_package_layout.py` — package and migration inclusion.

No implementation task edits `docs/roadmap.md`, `docs/status.md`, existing deployment records, or private runtime configuration.

---

### Task 1: Define Query Contracts and a Read-Only Route

**Files:**
- Create: `src/anlan/business_query/__init__.py`
- Create: `src/anlan/business_query/contracts.py`
- Modify: `src/anlan/conversation/contracts.py`
- Modify: `src/anlan/conversation/policy.py`
- Test: `tests/test_conversation_policy.py`
- Test: `tests/test_business_query.py`

- [ ] **Step 1: Write failing contract and routing tests**

Add tests that assert every query intent maps to one query type, produces `EXECUTE_BUSINESS_QUERY`, preserves an optional explicit target, and never sets `business_write`:

```python
@pytest.mark.parametrize(
    ("intent", "query_type"),
    [
        ("query_application_status", "application_status"),
        ("query_application_details", "application_details"),
        ("query_process_guidance", "process_guidance"),
        ("query_safety_knowledge", "safety_knowledge"),
    ],
)
def test_business_queries_are_read_only_in_every_state(intent, query_type):
    for state in (
        ConversationState(conversation_id="c", revision=1),
        ConversationState(
            conversation_id="c", revision=2, status="active_hot_work",
            active_task_id="task-current",
        ),
        ConversationState(
            conversation_id="c", revision=3, status="paused",
            active_task_id="task-current",
        ),
    ):
        route = decide(state, IntentProposal(
            intent=intent,
            target_task_id="task-explicit",
            user_explanation="只读查询",
            classifier_version="test-v1",
        ))
        assert route.action is RouteAction.EXECUTE_BUSINESS_QUERY
        assert route.query_type == query_type
        assert route.target_task_id == "task-explicit"
        assert route.business_write is False
```

Add strict-model tests that reject unknown query types, overlong questions, citation objects without a source, and evidence bundles with non-positive revisions.

- [ ] **Step 2: Run the tests and verify the missing contracts fail**

Run:

```powershell
uv run pytest tests/test_conversation_policy.py tests/test_business_query.py -q
```

Expected: FAIL during import because `anlan.business_query.contracts`, query intents, and `EXECUTE_BUSINESS_QUERY` do not exist.

- [ ] **Step 3: Implement strict query and evidence contracts**

Create `src/anlan/business_query/contracts.py` with these public shapes:

```python
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from anlan.common.models import NonEmpty, StrictModel

QueryType = Literal[
    "application_status", "application_details",
    "process_guidance", "safety_knowledge",
]
QueryText = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=True, min_length=1, max_length=500,
)]

class EvidenceFact(StrictModel):
    key: NonEmpty
    value: str | int | list[str] | dict[str, str]
    source: Literal[
        "material_checkpoint", "collaboration_application",
        "collaboration_policy", "knowledge_store",
    ]

class EvidenceCitation(StrictModel):
    chunk_id: NonEmpty
    doc_id: NonEmpty
    version: int = Field(strict=True, ge=1)
    title: NonEmpty
    source: NonEmpty
    quote: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
    content_hash: NonEmpty
    document_hash: NonEmpty
    valid_from: AwareDatetime
    valid_until: AwareDatetime

class EvidenceBundle(StrictModel):
    schema_version: Literal["business-evidence-v1"] = "business-evidence-v1"
    query_type: QueryType
    task_id: NonEmpty | None = None
    material_revision: int | None = Field(default=None, strict=True, ge=1)
    application_version: int | None = Field(default=None, strict=True, ge=1)
    observed_at: AwareDatetime
    facts: list[EvidenceFact] = Field(default_factory=list, max_length=32)
    citations: list[EvidenceCitation] = Field(default_factory=list, max_length=3)
    allowed_actions: list[NonEmpty] = Field(default_factory=list, max_length=12)
    limitations: list[NonEmpty] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def application_versions_move_together(self):
        values = (self.task_id, self.material_revision, self.application_version)
        if self.query_type != "safety_knowledge" and any(v is None for v in values):
            raise ValueError("application queries require task and versions")
        return self

class QueryAnswer(StrictModel):
    text: NonEmpty
    evidence: EvidenceBundle | None = None
    requires_selection: bool = False
    candidate_tasks: list[dict[str, str | int]] = Field(default_factory=list, max_length=20)
    outcome: Literal["ok", "unknown", "selection_required", "error"]
```

Export the contracts from `src/anlan/business_query/__init__.py`.

- [ ] **Step 4: Add query intents and deterministic policy routing**

In `src/anlan/conversation/contracts.py`, extend `IntentKind` and add:

```python
BUSINESS_QUERY_INTENTS = {
    "query_application_status": "application_status",
    "query_application_details": "application_details",
    "query_process_guidance": "process_guidance",
    "query_safety_knowledge": "safety_knowledge",
}
```

In `src/anlan/conversation/policy.py`, add `RouteAction.EXECUTE_BUSINESS_QUERY`, add `query_type: QueryType | None` to `RouteDecision`, and route before the write-intent branches:

```python
if intent in BUSINESS_QUERY_INTENTS:
    return RouteDecision(
        action=RouteAction.EXECUTE_BUSINESS_QUERY,
        active_task_id=state.active_task_id,
        target_task_id=proposal.target_task_id,
        query_type=BUSINESS_QUERY_INTENTS[intent],
        business_write=False,
    )
```

Keep query actions out of every `_decision` call that passes `write=True`, and do not add them to any collaboration command map.

- [ ] **Step 5: Run contract and policy tests**

Run:

```powershell
uv run pytest tests/test_conversation_policy.py tests/test_business_query.py -q
```

Expected: PASS with all four query types proven read-only.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src/anlan/business_query src/anlan/conversation/contracts.py src/anlan/conversation/policy.py tests/test_conversation_policy.py tests/test_business_query.py
git commit -m "feat(query): define grounded read-only query contracts"
```

---

### Task 2: Classify Queries and Constrain Explicit Targets

**Files:**
- Modify: `src/anlan/llm/conversation.py`
- Modify: `src/anlan/conversation/service.py`
- Test: `tests/test_conversation_model.py`
- Test: `tests/test_conversation_service.py`

- [ ] **Step 1: Write failing scripted and provider-boundary tests**

Add cases for these exact classifications:

```python
@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("当前材料状态是什么？", "query_application_status"),
        ("当前还缺哪些材料？", "query_application_details"),
        ("为什么现在不能重新提交？", "query_process_guidance"),
        ("为什么动火前需要气体检测？", "query_safety_knowledge"),
    ],
)
async def test_scripted_classifier_routes_bounded_business_questions(text, intent):
    proposal = await ScriptedConversationModel().classify(context(text))
    assert proposal.intent == intent
    assert proposal.requires_confirmation is False
    assert proposal.fields == {}
```

Extend the fake DeepSeek response tests so the provider schema accepts the four query intents and the system prompt says queries are read-only and must not invent identity, versions, or evidence.

Add a host test where the model returns `target_task_id="foreign-task"` for text that does not contain that exact identifier; assert `_constrain_proposal` clears the target while keeping the query intent.

- [ ] **Step 2: Run tests and verify they fail on `casual_chat`**

```powershell
uv run pytest tests/test_conversation_model.py tests/test_conversation_service.py -q
```

Expected: FAIL because the scripted classifier returns `casual_chat` and the live prompt does not enumerate query intents.

- [ ] **Step 3: Add a bounded scripted query classifier**

Add a helper before the existing material-write branches:

```python
def _scripted_query_intent(text: str) -> str | None:
    if any(phrase in text for phrase in ("材料状态", "申请状态", "当前进度", "轮到谁")):
        return "query_application_status"
    if any(phrase in text for phrase in ("缺哪些", "作业对象是什么", "作业位置是什么",
                                         "作业方式是什么", "附件是什么")):
        return "query_application_details"
    if any(phrase in text for phrase in ("下一步", "为什么不能", "怎么提交", "如何重新提交")):
        return "query_process_guidance"
    if "？" in text or "?" in text:
        if any(phrase in text for phrase in ("动火", "气体检测", "防护", "焊接", "切割")):
            return "query_safety_knowledge"
    return None
```

When the helper returns an intent, return an `IntentProposal` with empty fields and `requires_confirmation=False`. Keep explicit write sentences on existing paths.

- [ ] **Step 4: Extend the live classifier prompt and host constraint**

Add the four intent names to `_ProviderIntentProposal`'s documented enum and tell the provider:

```text
状态、详情、流程和安全知识问题分别使用四个 query_* intent；查询不得携带 fields，
不得声称已修改任务。target_task_id 只有在用户原文明确包含同一标识时才可返回。
```

In `ConversationService._constrain_proposal`, clear a query target not literally present in the current user text:

```python
if proposal.intent in BUSINESS_QUERY_INTENTS and proposal.target_task_id:
    if proposal.target_task_id not in text:
        proposal = proposal.model_copy(update={"target_task_id": None})
```

This check is in addition to, not a replacement for, gateway authorization.

- [ ] **Step 5: Run classifier and service constraint tests**

```powershell
uv run pytest tests/test_conversation_model.py tests/test_conversation_service.py -q
```

Expected: PASS; all questions remain read-only and invented targets are discarded.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/anlan/llm/conversation.py src/anlan/conversation/service.py tests/test_conversation_model.py tests/test_conversation_service.py
git commit -m "feat(query): classify bounded business questions"
```

---

### Task 3: Build the Read-Only Gateway and Deterministic Answers

**Files:**
- Create: `src/anlan/business_query/service.py`
- Modify: `src/anlan/business_query/__init__.py`
- Modify: `src/anlan/interfaces/collaboration_conversation.py`
- Test: `tests/test_business_query.py`

- [ ] **Step 1: Write failing gateway tests with a fake authorized workflow**

Create a fake with `role`, `applications`, and `read` methods. Add tests proving:

```python
async def test_status_answer_uses_current_shared_projection_and_versions():
    answer = await service.answer(
        APPLICANT, query_type="application_status", question="当前材料状态是什么？",
        active_task_id="task-1", explicit_task_id=None,
    )
    assert answer.outcome == "ok"
    assert answer.evidence.task_id == "task-1"
    assert answer.evidence.material_revision == 3
    assert answer.evidence.application_version == 2
    assert "要求补充" in answer.text
    assert "附件说明" in answer.text
    assert workflow.read_calls == [(APPLICANT, "task-1")]
    assert workflow.write_calls == []
```

Add separate tests for details, process guidance, explicit authorized target, unauthorized target propagation, and a reviewer projection that never includes applicant private messages.

Add target-resolution tests:

- no active target plus zero accessible applications returns `unknown`;
- one accessible application returns `selection_required` and does not bind it;
- multiple applications return at most 20 bounded summaries;
- an active target wins unless the user supplies an explicit authorized target.

- [ ] **Step 2: Run gateway tests and verify the service is missing**

```powershell
uv run pytest tests/test_business_query.py -q
```

Expected: FAIL importing `BusinessQueryService`.

- [ ] **Step 3: Expose authorized application summaries from the workflow adapter**

Add this method to `CollaborationConversationAdapter`:

```python
async def applications(self, actor):
    result = await self.service.list(actor)
    return [
        {
            "task_id": item.task_id,
            "status": item.status,
            "version": item.version,
            "updated_at": item.updated_at.isoformat() if item.updated_at else "",
        }
        for item in result["items"][:20]
    ]
```

Do not return applicant/reviewer identifiers, materials, events, or conversation IDs in the selection summary.

- [ ] **Step 4: Implement target resolution and evidence creation**

Create `BusinessQueryService` with this interface:

```python
from pydantic import TypeAdapter

from anlan.business_query.contracts import QueryAnswer, QueryText, QueryType

class BusinessQueryService:
    def __init__(self, workflow, *, clock=None, knowledge_provider=None, audit=None):
        self.workflow = workflow
        self.clock = clock or (lambda: datetime.now(UTC))
        self.knowledge_provider = knowledge_provider
        self.audit = audit

    async def answer(
        self, actor, *, query_type: QueryType, question: str,
        active_task_id: str | None, explicit_task_id: str | None,
        source_message_id: str | None = None,
    ) -> QueryAnswer:
        query_type = TypeAdapter(QueryType).validate_python(query_type)
        question = TypeAdapter(QueryText).validate_python(question)
        if query_type == "safety_knowledge":
            return await self._answer_knowledge(actor, question)
        target = explicit_task_id or active_task_id
        if target is None:
            return await self._selection_answer(actor)
        result = await self.workflow.read(actor, target)
        bundle = self._application_evidence(query_type, result.projection)
        return self._compose_application(bundle)
```

For application queries, resolve the target, call `workflow.read(actor, task_id)` exactly once, and build facts only from `WorkflowResult.projection.model_dump(mode="json")`. Read these keys:

```python
projection["status"]
projection["revision"]
projection["fields"]
projection["missing_fields"]
projection["collaboration"]["application"]["status"]
projection["collaboration"]["application"]["version"]
projection["collaboration"]["allowed_actions"]
```

Never inspect the conversation store, raw checkpoint history, prompts, traces, route records, or another user's messages.

- [ ] **Step 5: Implement deterministic status, detail, and process composition**

Use explicit Chinese labels from `LABELS`. Map collaboration states as follows:

```python
APPLICATION_LABELS = {
    "draft": "草稿",
    "under_review": "安全审核中",
    "changes_requested": "要求补充",
    "review_completed": "材料核查完成",
}
PROCESS_GUIDANCE = {
    "draft": "补齐材料后可选择安全审核人员并提交。",
    "under_review": "当前等待指定安全审核人员核查，材料已冻结。",
    "changes_requested": "按补充要求更新材料，完成分析后可重新提交。",
    "review_completed": "本轮材料核查已完成；这不代表作业批准或开工授权。",
}
```

Every successful answer must include task ID, material revision, application version, and `observed_at`. Missing or malformed projection data must return `outcome="error"`; it must not call a generic responder.

- [ ] **Step 6: Run the pure gateway tests**

```powershell
uv run pytest tests/test_business_query.py -q
```

Expected: PASS for target selection, status, details, process guidance, and zero writes.

- [ ] **Step 7: Commit Task 3**

```powershell
git add src/anlan/business_query src/anlan/interfaces/collaboration_conversation.py tests/test_business_query.py
git commit -m "feat(query): add authorized read-only query gateway"
```

---

### Task 4: Integrate Private Query Answers into Conversations

**Files:**
- Modify: `src/anlan/conversation/service.py`
- Modify: `src/anlan/interfaces/api.py`
- Test: `tests/test_conversation_service.py`
- Test: `tests/test_collaboration_conversation.py`

- [ ] **Step 1: Write failing orchestration tests**

In `tests/test_conversation_service.py`, inject a fake query service and assert:

```python
async def test_query_route_calls_gateway_not_chat_responder_or_workflow_write():
    result = await subject.message(
        OWNER, conversation["conversation_id"], request_id=unique("query"),
        expected_revision=conversation["revision"], text="当前材料状态是什么？",
    )
    assert fake_queries.calls[0]["source_message_id"]
    assert result["messages"][-1]["text"] == "申请 task-1 当前为要求补充。"
    assert model.respond_calls == 0
    assert workflow.calls == []
```

Add a failure test asserting a query-gateway exception becomes a sanitized durable `query_failure`, leaves the current task binding unchanged, and makes zero business writes.

In `tests/test_collaboration_conversation.py`, complete a real two-role flow, then ask both roles for status. Assert both answers contain the same task/material/application versions, each answer exists only in the caller's conversation, and applicant/reviewer private sentinel messages do not cross.

- [ ] **Step 2: Run the conversation tests and verify the route is unhandled**

```powershell
uv run pytest tests/test_conversation_service.py tests/test_collaboration_conversation.py -q
```

Expected: FAIL because `EXECUTE_BUSINESS_QUERY` is not implemented by `ConversationService._execute`.

- [ ] **Step 3: Inject and execute the query service**

Change the constructor to require a query service in production while allowing an explicit test double:

```python
def __init__(self, store, model_factory, workflow, business_queries=None):
    self.store = store
    self._model_factory = model_factory
    self.workflow = workflow
    self.business_queries = business_queries
```

In `_execute`, add this branch before `REPLY_ONLY`:

```python
elif action is RouteAction.EXECUTE_BUSINESS_QUERY:
    if self.business_queries is None or decision.query_type is None:
        raise InvalidTransition("业务查询服务未配置")
    answer = await self.business_queries.answer(
        identity,
        query_type=decision.query_type,
        question=reservation["text"],
        active_task_id=raw["active_task_id"],
        explicit_task_id=decision.target_task_id,
        source_message_id=message_id,
    )
    assistant = answer.text
```

Classify exceptions from this branch as `query_failure`; never fall through to `ChatResponder`.

- [ ] **Step 4: Compose production services once**

In `create_app`, create one collaboration workflow adapter and pass it to both query and conversation services:

```python
workflow_adapter = CollaborationConversationAdapter(
    collaboration, WorkflowAdapter(models.material_service),
)
business_queries = BusinessQueryService(
    workflow_adapter,
    clock=clock,
    knowledge_provider=lambda: app.state.knowledge,
)
conversation_service = ConversationService(
    conversations, models.conversation, workflow_adapter, business_queries,
)
```

Do not create a second collaboration service, do not pass `app.state.knowledge` before lifespan initialization, and do not expose query internals through the HTTP request body.

- [ ] **Step 5: Run unit and real-PG collaboration tests**

```powershell
uv run pytest tests/test_conversation_service.py tests/test_collaboration_conversation.py -q
```

Expected: PASS; status answers are private, grounded, and read-only for both roles.

- [ ] **Step 6: Commit Task 4**

```powershell
git add src/anlan/conversation/service.py src/anlan/interfaces/api.py tests/test_conversation_service.py tests/test_collaboration_conversation.py
git commit -m "feat(query): answer grounded queries in private conversations"
```

---

### Task 5: Add Cited Safety-Knowledge Answers

**Files:**
- Modify: `src/anlan/business_query/service.py`
- Modify: `src/anlan/business_query/contracts.py`
- Test: `tests/test_business_query.py`
- Test: `tests/test_collaboration_conversation.py`

- [ ] **Step 1: Write failing knowledge-grounding tests**

Use a fake knowledge store that returns one valid citation and assert:

```python
async def test_safety_answer_contains_only_retrieved_claim_and_citation():
    answer = await service.answer(
        APPLICANT,
        query_type="safety_knowledge",
        question="为什么动火前需要气体检测？",
        active_task_id=None,
        explicit_task_id=None,
    )
    assert answer.outcome == "ok"
    assert answer.evidence.task_id is None
    assert answer.evidence.citations[0].chunk_id == "chunk-1"
    assert "受限空间" not in answer.text
    assert "可燃气体" in answer.text
```

Add tests for `no_eligible_evidence`, timeout/unavailable, revoked ACL, expired citations, and a citation missing required hashes. Every case must return `unknown` or `error` without calling a generic model.

- [ ] **Step 2: Run tests and verify safety queries lack evidence**

```powershell
uv run pytest tests/test_business_query.py -q
```

Expected: FAIL because safety queries are not implemented.

- [ ] **Step 3: Reuse the existing bounded knowledge tool**

In `BusinessQueryService.answer`, handle `safety_knowledge` without requiring an application target:

```python
observation = await query_knowledge(
    self.knowledge_provider(), actor, {"question": question},
)
if observation.outcome != "ok" or not observation.citations:
    return QueryAnswer(
        text="当前知识库没有足够依据回答这个问题。",
        evidence=EvidenceBundle(
            query_type="safety_knowledge",
            observed_at=self.clock(),
            limitations=[observation.reason or "no_eligible_evidence"],
        ),
        outcome="unknown" if observation.outcome == "unknown" else "error",
    )
```

Convert at most three returned citations into `EvidenceCitation`. Preserve document/chunk hashes and validity metadata already enforced by `KnowledgeStore`; reject incomplete citation dictionaries instead of inventing defaults.

- [ ] **Step 4: Compose a deterministic cited answer**

Use the first retrieved quote as the only substantive claim:

```python
primary = bundle.citations[0]
text = (
    f"根据《{primary.title}》的当前可用依据：{primary.quote}"
    f"（引用 {primary.doc_id}/{primary.chunk_id}）。该说明用于材料准备，"
    "不代表作业批准或开工授权。"
)
```

Do not call `DeepSeekChatResponder` for knowledge synthesis in this phase. This keeps every returned claim mechanically traceable to the citation; a future composer can be added only with citation-validation tests.

- [ ] **Step 5: Run knowledge and collaboration tests**

```powershell
uv run pytest tests/test_business_query.py tests/test_collaboration_conversation.py -q
```

Expected: PASS; evidence-backed answers contain citations and missing evidence produces an explicit refusal.

- [ ] **Step 6: Commit Task 5**

```powershell
git add src/anlan/business_query tests/test_business_query.py tests/test_collaboration_conversation.py
git commit -m "feat(query): ground safety answers in cited knowledge"
```

---

### Task 6: Separate Mixed Queries from Follow-Up Writes

**Files:**
- Modify: `src/anlan/conversation/contracts.py`
- Modify: `src/anlan/conversation/policy.py`
- Modify: `src/anlan/conversation/service.py`
- Modify: `src/anlan/llm/conversation.py`
- Modify: `src/anlan/interfaces/collaboration_conversation.py`
- Test: `tests/test_conversation_model.py`
- Test: `tests/test_conversation_service.py`
- Test: `tests/test_collaboration_conversation.py`

- [ ] **Step 1: Write failing mixed-intent tests**

Cover these behaviors:

```python
async def test_query_and_material_change_answers_then_waits_for_confirmation():
    result = await say(
        applicant, conversation,
        "当前材料状态是什么？另外把作业位置改成二号罐区。",
    )
    assert "当前" in result["messages"][-1]["text"]
    assert result["pending_intent"]["kind"] == "task_input_candidate"
    assert result["pending_intent"]["fields"] == {
        "work_location_description": "二号罐区",
    }
    assert material_revision(task) == 1
```

Then send `确认` and assert the material revision changes exactly once. Add reviewer tests proving a mixed query plus material edit produces only the query answer and a safe refusal, never a pending material candidate. Add a mixed query plus collaboration command test proving the collaboration payload is frozen with task/material/application versions before confirmation.

- [ ] **Step 2: Run mixed-intent tests and verify the write portion is lost or misrouted**

```powershell
uv run pytest tests/test_conversation_model.py tests/test_conversation_service.py tests/test_collaboration_conversation.py -q
```

Expected: FAIL because `IntentProposal` cannot carry a separate follow-up write.

- [ ] **Step 3: Add strict unfrozen and frozen follow-up contracts**

In `conversation/contracts.py`, add:

```python
class QueryWriteCandidate(StrictModel):
    intent: Literal[
        "task_input_candidate", "submit_application", "request_changes",
        "resubmit_application", "complete_material_review",
    ]
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    collaboration: CollaborationInput | None = None

class FrozenQueryFollowUp(StrictModel):
    intent: Literal[
        "task_input_candidate", "submit_application", "request_changes",
        "resubmit_application", "complete_material_review",
    ]
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    collaboration: FrozenCollaborationCommand | None = None
```

Add `query_write: QueryWriteCandidate | None` to `IntentProposal` and `query_follow_up: FrozenQueryFollowUp | None` to `RouteDecision`. Validation must require `query_write` only when the primary intent is in `BUSINESS_QUERY_INTENTS`.

- [ ] **Step 4: Freeze the follow-up through existing policy and collaboration adapters**

Add a `ConversationService._freeze_query_follow_up` helper that:

1. Converts `QueryWriteCandidate` into a separate `IntentProposal` with `requires_confirmation=True`.
2. Runs `workflow.constrain(identity, candidate)`.
3. Runs `decide(state, candidate)`.
4. Accepts only `ASK_TASK_INPUT_CONFIRMATION` or `ASK_COLLABORATION_CONFIRMATION`.
5. Calls `workflow.freeze` for collaboration candidates.
6. Returns `FrozenQueryFollowUp` or `None` for a forbidden reviewer material write.

Never accept `SUBMIT_TASK_INPUT`, `START_HOT_WORK`, `EXECUTE_COLLABORATION`, or another query as a follow-up.

- [ ] **Step 5: Persist the answer and independent pending candidate**

After the gateway returns the query answer, call `set_pending_intent` only when a validated `query_follow_up` exists:

```python
if decision.query_follow_up is not None:
    await self.store.set_pending_intent(
        identity,
        conversation_id,
        message_id,
        decision.query_follow_up.model_dump(mode="json"),
    )
    assistant += " 另有一项修改待你确认；确认前不会写入业务状态。"
```

The query answer remains the assistant message; the follow-up uses the existing pending-intent confirmation path and idempotency behavior.

- [ ] **Step 6: Extend scripted/live classification for mixed messages**

For scripted mode, if `_scripted_query_intent(text)` returns a query and `_scripted_material_fields(text)` returns fields, attach:

```python
query_write=QueryWriteCandidate(
    intent="task_input_candidate",
    fields=extracted,
)
```

Extend the provider JSON schema with a nullable `query_write`, and state that it is only a candidate; the host always validates and freezes it. Do not let the provider supply versions, identity, request IDs, or adopted citations.

- [ ] **Step 7: Run mixed-intent and regression tests**

```powershell
uv run pytest tests/test_conversation_model.py tests/test_conversation_policy.py tests/test_conversation_service.py tests/test_collaboration_conversation.py -q
```

Expected: PASS; query text is answered, follow-up writes remain pending, and reviewers cannot obtain applicant write capability.

- [ ] **Step 8: Commit Task 6**

```powershell
git add src/anlan/conversation src/anlan/llm/conversation.py src/anlan/interfaces/collaboration_conversation.py tests/test_conversation_model.py tests/test_conversation_policy.py tests/test_conversation_service.py tests/test_collaboration_conversation.py
git commit -m "feat(query): isolate mixed questions from confirmed writes"
```

---

### Task 7: Persist Minimal Query Audit Receipts

**Files:**
- Create: `src/anlan/sql/021_business_queries.sql`
- Create: `src/anlan/infrastructure/business_queries.py`
- Modify: `src/anlan/infrastructure/postgres.py`
- Modify: `src/anlan/interfaces/api.py`
- Modify: `src/anlan/business_query/service.py`
- Modify: `tests/test_package_layout.py`
- Test: `tests/test_business_query_audit.py`

- [ ] **Step 1: Write failing real-PostgreSQL audit tests**

Test initialization, one receipt per source message, same-payload replay, conflicting replay rejection, tenant/user isolation, and absence of raw question/evidence text:

```python
async def test_query_receipt_is_minimal_idempotent_and_private(dsn):
    store = BusinessQueryAuditStore(dsn)
    await store.initialize()
    receipt = QueryReceipt(
        source_message_id="message-1",
        task_id="task-1",
        query_type="application_status",
        material_revision=3,
        application_version=2,
        evidence_schema_version="business-evidence-v1",
        citation_ids=[],
        outcome="ok",
    )
    await store.record(APPLICANT, "applicant", receipt)
    await store.record(APPLICANT, "applicant", receipt)
    row = await store.get(APPLICANT, "message-1")
    assert row["task_id"] == "task-1"
    assert "question" not in row
    assert "facts" not in row
    assert "answer" not in row
```

- [ ] **Step 2: Run audit tests and verify the migration/store are missing**

```powershell
uv run pytest tests/test_business_query_audit.py tests/test_package_layout.py -q
```

Expected: FAIL importing `BusinessQueryAuditStore` and finding SQL migration 021.

- [ ] **Step 3: Add the additive audit migration**

Create `021_business_queries.sql` with an explicitly bounded table:

```sql
CREATE TABLE IF NOT EXISTS anlan_v2.business_query_receipts (
    tenant_id text NOT NULL CHECK (char_length(btrim(tenant_id)) BETWEEN 1 AND 500),
    actor_user_id text NOT NULL CHECK (char_length(btrim(actor_user_id)) BETWEEN 1 AND 500),
    source_message_id text NOT NULL CHECK (
        char_length(btrim(source_message_id)) BETWEEN 1 AND 500
    ),
    actor_role text CHECK (actor_role IN ('applicant','safety_manager')),
    task_id text CHECK (char_length(btrim(task_id)) BETWEEN 1 AND 500),
    query_type text NOT NULL CHECK (query_type IN (
        'application_status','application_details','process_guidance','safety_knowledge'
    )),
    material_revision integer CHECK (material_revision >= 1),
    application_version integer CHECK (application_version >= 1),
    evidence_schema_version text NOT NULL CHECK (
        evidence_schema_version = 'business-evidence-v1'
    ),
    citation_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(citation_ids) = 'array' AND jsonb_array_length(citation_ids) <= 3
    ),
    outcome text NOT NULL CHECK (outcome IN ('ok','unknown','selection_required','error')),
    queried_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,actor_user_id,source_message_id),
    CHECK (
        (task_id IS NULL AND material_revision IS NULL AND application_version IS NULL)
        OR (task_id IS NOT NULL AND material_revision IS NOT NULL
            AND application_version IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS business_query_receipts_task
    ON anlan_v2.business_query_receipts(tenant_id,task_id,queried_at);

INSERT INTO anlan_v2.anlan_schema_migrations(version)
VALUES (21) ON CONFLICT DO NOTHING;
```

- [ ] **Step 4: Implement an idempotent audit store**

Use `importlib.resources.files("anlan")`, `conninfo`, `AsyncConnection`, and `Jsonb`, following `ConversationStore` and `CollaborationStore`. `record` must select any existing receipt under the same actor/message key and:

- return it when all persisted fields match;
- raise `InvalidTransition` when the same key has different query metadata;
- never accept question text, answer text, facts, or full citations in its contract.

- [ ] **Step 5: Initialize and call the audit store**

Initialize the store through `initialize_database` and app lifespan. Inject it into `BusinessQueryService`. Record after the evidence/answer outcome is finalized and before returning the answer. For `selection_required` and knowledge answers without a task, keep all version fields null; for application answers require all three target/version fields.

Audit failure must return sanitized `query_failure` rather than silently producing an unaudited answer.

- [ ] **Step 6: Run audit and package tests**

```powershell
uv run pytest tests/test_business_query_audit.py tests/test_package_layout.py -q
```

Expected: PASS with migration 021 included in the wheel resources and no raw content in receipts.

- [ ] **Step 7: Commit Task 7**

```powershell
git add src/anlan/sql/021_business_queries.sql src/anlan/infrastructure/business_queries.py src/anlan/infrastructure/postgres.py src/anlan/interfaces/api.py src/anlan/business_query/service.py tests/test_business_query_audit.py tests/test_package_layout.py
git commit -m "feat(query): persist minimal query audit receipts"
```

---

### Task 8: Freeze Evaluation Cases and Run Full Verification

**Files:**
- Create: `evals/business-query-v1/README.md`
- Create: `evals/business-query-v1/cases.json`
- Create: `tests/test_business_query_evaluation.py`
- Modify: `tests/test_collaboration_conversation.py`

- [ ] **Step 1: Write the frozen evaluation manifest**

Create at least these slices, with explicit expected query type, maximum business writes, required evidence keys, and forbidden output markers:

```json
[
  {
    "case_id": "status-001",
    "slice": "application_status",
    "role": "applicant",
    "input": "当前材料状态是什么？",
    "expected_query_type": "application_status",
    "required_evidence_keys": ["application_status", "missing_fields"],
    "max_business_writes": 0,
    "forbidden_markers": ["PRIVATE-", "approved", "permit_issued"]
  },
  {
    "case_id": "knowledge-unknown-001",
    "slice": "knowledge_unknown",
    "role": "safety_manager",
    "input": "知识库没有收录的特殊工艺可以直接开工吗？",
    "expected_query_type": "safety_knowledge",
    "expected_outcome": "unknown",
    "max_business_writes": 0,
    "forbidden_markers": ["可以直接开工"]
  },
  {
    "case_id": "mixed-001",
    "slice": "mixed_query_write",
    "role": "applicant",
    "input": "当前状态是什么？把位置改成二号罐区。",
    "expected_query_type": "application_status",
    "expected_pending_kind": "task_input_candidate",
    "max_business_writes": 0,
    "forbidden_markers": ["已修改"]
  }
]
```

Also include application details, process guidance, no target, one target, multiple targets, explicit unauthorized target, reviewer material write, cross-tenant access, quoted instructions, negation, and prompt injection.

- [ ] **Step 2: Write the evaluation contract test and verify it initially fails**

The test must validate unique case IDs, required keys per slice, bounded input length, expected outcomes, zero unconfirmed writes, and forbidden output markers. Run:

```powershell
uv run pytest tests/test_business_query_evaluation.py -q
```

Expected: FAIL until the frozen cases and evaluator assertions are complete.

- [ ] **Step 3: Add final two-browser isolation assertions**

Extend the real collaboration test to assert:

- applicant asks status after entering a private casual question;
- reviewer asks the same status after submission;
- both see the same authorized shared versions;
- neither sees the other's question or answer;
- `/tasks/{task}/history` remains owner-only for the reviewer;
- query audit rows contain only the bounded receipt metadata;
- material, application, collaboration-command, event, and notification counts do not change for read-only queries.

- [ ] **Step 4: Run focused verification**

```powershell
uv run ruff check src/anlan/business_query src/anlan/conversation src/anlan/interfaces/api.py src/anlan/interfaces/collaboration_conversation.py src/anlan/infrastructure/business_queries.py tests/test_business_query.py tests/test_business_query_audit.py tests/test_business_query_evaluation.py tests/test_conversation_model.py tests/test_conversation_policy.py tests/test_conversation_service.py tests/test_collaboration_conversation.py
uv run pytest tests/test_business_query.py tests/test_business_query_audit.py tests/test_business_query_evaluation.py tests/test_conversation_model.py tests/test_conversation_policy.py tests/test_conversation_service.py tests/test_collaboration_conversation.py tests/test_package_layout.py -q
```

Expected: Ruff exits 0; pytest reports zero failures and zero skips.

- [ ] **Step 5: Run full repository verification**

Choose a new evidence path that does not already exist:

```powershell
uv lock --check
uv run python scripts/ci.py --output .runtime/business-query-ci.json
```

Expected: `uv lock --check` exits 0. CI prints JSON with `"status":"passed"`; lint, tests, and source-integrity checks all return 0; the JUnit summary has zero failures, errors, and skips.

- [ ] **Step 6: Review the implementation against the approved design**

Read `docs/superpowers/specs/2026-11-01-business-query-design.md` and confirm:

- every business claim comes from current authorized data or a citation;
- private messages never enter shared evidence or another role's answer;
- no read-only query changes business state;
- target selection never auto-binds;
- knowledge failure never falls back to model knowledge;
- Skill packaging remains unimplemented and only stable contracts were created.

Record any mismatch as a failing test and fix it before committing.

- [ ] **Step 7: Commit Task 8**

```powershell
git add evals/business-query-v1 tests/test_business_query_evaluation.py tests/test_collaboration_conversation.py
git commit -m "test(query): freeze grounded query acceptance"
```

- [ ] **Step 8: Prepare the independent implementation handoff**

In the implementation chat, report:

- branch/worktree path;
- commit list for Tasks 1–8;
- focused-test totals;
- full CI evidence path and SHA-256;
- any intentionally deferred Skill work;
- confirmation that no deployment or live-model request occurred.

Do not merge, deploy, or delete the worktree without a separate user instruction.
