# Conversational Hot-Work Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the form-first console with a persistent chat entry that safely distinguishes casual conversation from hot-work requests, requires confirmation before business writes, and reuses the existing material workflow behind a task sidebar.

**Architecture:** Add a conversation package in front of the existing workflow. A model proposes a bounded structured intent, deterministic policy owns confirmation and routing, and a workflow adapter is the only component allowed to call `start`, `resume`, `revise`, or `recover`; PostgreSQL persists messages, pending intents, routes, idempotency, and the active task. The browser submits messages to one conversation API and renders server-owned chat and task projections.

**Tech Stack:** Python 3.13, Pydantic 2, FastAPI, PostgreSQL/psycopg 3, existing LangGraph material workflow, DeepSeek through the existing bounded gateway and budget ledger, vanilla HTML/CSS/JavaScript, pytest, Ruff.

---

## File map and execution constraints

New backend units are deliberately small and do not move existing workflow code:

- `src/anlan/conversation/contracts.py`: persisted and model-facing Pydantic contracts.
- `src/anlan/conversation/policy.py`: pure deterministic routing decisions; no database or model imports.
- `src/anlan/conversation/service.py`: one-message orchestration and recovery.
- `src/anlan/infrastructure/conversations.py`: PostgreSQL repository, locks, revisions, and idempotency.
- `src/anlan/llm/conversation.py`: scripted and DeepSeek classifier/chat implementations with bounded context.
- `src/anlan/interfaces/conversation_routes.py`: authenticated HTTP and SSE adapters.
- `src/anlan/interfaces/conversation_runtime.py`: existing material service adapter and sidebar projection.
- `src/anlan/sql/013_conversations.sql`: conversation schema. Migration `012` remains reserved by the already-planned dynamic MCP work.
- `src/anlan/sql/014_conversation_budget.sql`: adds a distinct conversation work-package identifier without resetting attempts or limits.
- `evals/conversation-routing-v1/`: versioned routing cases and deterministic scorer.

Implementation starts in scripted mode. SQL014 and live provider wiring may be implemented and tested with a fake ledger, but no real model request is allowed until the user explicitly confirms a new conversation work package and its remaining shared-budget impact. Never spend the two remaining `P8-WP04` calls on conversation development.

The working tree already contains unrelated changes in `docs/roadmap.md`, `docs/status.md`, `docs/phases/phase-10-dynamic-mcp/`, and `tests/test_tool_loop_live.py`. Every commit below must stage only the paths named by that task. Do not stage `.superpowers/` mockups.

### Task 1: Define conversation contracts and the deterministic policy

**Files:**
- Create: `src/anlan/conversation/__init__.py`
- Create: `src/anlan/conversation/contracts.py`
- Create: `src/anlan/conversation/policy.py`
- Test: `tests/test_conversation_policy.py`

- [ ] **Step 1: Write failing contract and policy tests**

Create tests that prove confirmation and business-write boundaries before any persistence exists:

```python
from anlan.conversation.contracts import ConversationState, IntentProposal
from anlan.conversation.policy import RouteAction, decide


def proposal(intent, *, fields=None, requires_confirmation=False):
    return IntentProposal(
        intent=intent,
        fields=fields or {},
        requires_confirmation=requires_confirmation,
        user_explanation="bounded explanation",
        classifier_version="scripted-intent-v1",
    )


def test_hot_work_candidate_never_starts_without_confirmation():
    state = ConversationState(conversation_id="conv-1", revision=1)
    route = decide(state, proposal(
        "hot_work_candidate",
        fields={"work_object_description": "V101 管线补焊"},
        requires_confirmation=True,
    ))
    assert route.action == RouteAction.ASK_CONFIRMATION
    assert route.business_write is False


def test_confirmation_starts_only_the_saved_pending_intent():
    state = ConversationState.model_validate({
        "conversation_id": "conv-1",
        "revision": 2,
        "status": "pending_confirmation",
        "pending_intent": {
            "intent_id": "intent-1",
            "kind": "hot_work_candidate",
            "fields": {"work_object_description": "V101 管线补焊"},
            "revision": 1,
        },
    })
    route = decide(state, proposal("confirm_pending_intent"))
    assert route.action == RouteAction.START_HOT_WORK
    assert route.fields == {"work_object_description": "V101 管线补焊"}
    assert route.business_write is True


def test_casual_chat_during_active_task_preserves_binding():
    state = ConversationState(
        conversation_id="conv-1", revision=3,
        status="active_hot_work", active_task_id="task-1",
    )
    route = decide(state, proposal("casual_chat"))
    assert route.action == RouteAction.REPLY_ONLY
    assert route.active_task_id == "task-1"
    assert route.business_write is False
```

Also cover rejection, amendment of a pending candidate, explicit pause/resume, `cancel_task` detaching the conversation without changing the business task, ambiguous `task_input_candidate`, and a new request while a task is active.

- [ ] **Step 2: Run the policy tests and verify they fail for missing modules**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_policy.py -q
```

Expected: collection fails because `anlan.conversation` does not exist.

- [ ] **Step 3: Implement strict contracts**

Create bounded literals and models; keep model proposals separate from trusted identity and task IDs:

```python
# src/anlan/conversation/contracts.py
from typing import Literal

from pydantic import Field

from anlan.common.models import NonEmpty, StrictModel
from anlan.workflows.material_contracts import FieldName, Text

IntentKind = Literal[
    "casual_chat", "hot_work_candidate", "confirm_pending_intent",
    "reject_pending_intent", "task_input_candidate", "pause_task",
    "resume_task", "cancel_task", "switch_or_create_task",
]
ConversationStatus = Literal["idle", "pending_confirmation", "active_hot_work", "paused"]


class PendingIntent(StrictModel):
    intent_id: NonEmpty
    kind: Literal["hot_work_candidate", "task_input_candidate", "switch_or_create_task"]
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    revision: int = Field(strict=True, ge=1)


class ConversationState(StrictModel):
    conversation_id: NonEmpty
    revision: int = Field(strict=True, ge=1)
    status: ConversationStatus = "idle"
    active_task_id: str | None = None
    pending_intent: PendingIntent | None = None


class IntentProposal(StrictModel):
    intent: IntentKind
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    requires_confirmation: bool = False
    user_explanation: NonEmpty
    classifier_version: NonEmpty
```

Add `RouteAction` and a `RouteDecision` model in `policy.py`. `decide()` must reject impossible combinations with `InvalidTransition`, return `business_write=False` by default, and set it to true only for `START_HOT_WORK`, `SUBMIT_TASK_INPUT`, or an explicit `RECOVER_TASK` decision.

- [ ] **Step 4: Run tests and lint**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_policy.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/conversation tests/test_conversation_policy.py
```

Expected: all conversation policy tests pass and Ruff reports no diagnostics.

- [ ] **Step 5: Commit the contract and policy slice**

```powershell
git add src/anlan/conversation tests/test_conversation_policy.py
git commit -m "feat: define controlled conversation routing"
```

### Task 2: Persist conversations, messages, routes, and pending intents

**Files:**
- Create: `src/anlan/sql/013_conversations.sql`
- Create: `src/anlan/infrastructure/conversations.py`
- Test: `tests/test_conversation_store.py`
- Modify: `src/anlan/interfaces/api.py:91-98`

- [ ] **Step 1: Write PostgreSQL store tests first**

Cover tenant isolation, monotonically increasing message order, identical replay, changed-payload rejection, stale conversation revision, one active writer, and restart recovery:

```python
import pytest
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.conversations import ConversationStore

pytestmark = pytest.mark.postgres


def test_message_reservation_is_idempotent_and_rejects_changed_payload(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        await store.initialize()
        conversation = await store.create(OWNER, request_id="create-1")
        first = await store.reserve_message(
            OWNER, conversation["conversation_id"], "message-1", 1, "我要申请动火"
        )
        replay = await store.reserve_message(
            OWNER, conversation["conversation_id"], "message-1", 1, "我要申请动火"
        )
        assert replay == first
        with pytest.raises(InvalidTransition):
            await store.reserve_message(
                OWNER, conversation["conversation_id"], "message-1", 1, "changed"
            )
    run(scenario())


def test_other_identity_cannot_observe_conversation(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id="create-private")
        other = OWNER.model_copy(update={"user_id": "other"})
        with pytest.raises(AccessDenied):
            await store.get(other, conversation["conversation_id"])
    run(scenario())
```

- [ ] **Step 2: Run the store tests and verify the expected failure**

Run:

```powershell
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
.venv/Scripts/python.exe -m pytest tests/test_conversation_store.py -q
```

Expected: collection fails because `ConversationStore` and SQL013 do not exist.

- [ ] **Step 3: Add SQL013 with explicit constraints**

Create four tables and indexes. Store the visible message text separately from route metadata; do not store hidden reasoning:

```sql
CREATE TABLE IF NOT EXISTS anlan_v2.conversations (
    conversation_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    create_request_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('idle','pending_confirmation','active_hot_work','paused')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    active_task_id text,
    pending_intent_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id,user_id,create_request_id)
);
CREATE TABLE IF NOT EXISTS anlan_v2.conversation_messages (
    message_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES anlan_v2.conversations(conversation_id),
    request_id text NOT NULL,
    ordinal bigint GENERATED ALWAYS AS IDENTITY,
    role text NOT NULL CHECK (role IN ('user','assistant','system_event')),
    text text NOT NULL CHECK (octet_length(text) BETWEEN 1 AND 8192),
    status text NOT NULL CHECK (status IN ('pending','completed','failed')),
    request_payload jsonb,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (conversation_id,request_id)
);
CREATE TABLE IF NOT EXISTS anlan_v2.pending_intents (
    intent_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES anlan_v2.conversations(conversation_id),
    source_message_id text NOT NULL REFERENCES anlan_v2.conversation_messages(message_id),
    revision integer NOT NULL CHECK (revision >= 1),
    status text NOT NULL CHECK (status IN ('pending','confirmed','rejected','superseded')),
    candidate jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS anlan_v2.conversation_routes (
    message_id text PRIMARY KEY REFERENCES anlan_v2.conversation_messages(message_id),
    proposal jsonb NOT NULL,
    decision jsonb NOT NULL,
    classifier_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS conversation_owner_updated
    ON anlan_v2.conversations(tenant_id,user_id,updated_at DESC);
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (13) ON CONFLICT DO NOTHING;
```

Before executing SQL013, update `conversations.pending_intent_id` with a deferred foreign key only after `pending_intents` exists, or keep the reference application-enforced and test that no dangling ID is returned. Do not introduce a circular immediate FK.

- [ ] **Step 4: Implement `ConversationStore` transaction and advisory-lock methods**

Use `conninfo(dsn)`, `dict_row`, JSONB, and identity-scoped queries like the existing event and perception stores. The public methods are:

```python
class ConversationStore:
    async def initialize(self) -> None: ...
    async def create(self, identity, request_id: str) -> dict: ...
    async def list(self, identity, limit: int = 20) -> list[dict]: ...
    async def get(self, identity, conversation_id: str, *, conn=None, lock=False) -> dict: ...
    async def reserve_message(
        self, identity, conversation_id: str, request_id: str,
        expected_revision: int, text: str,
    ) -> dict: ...
    async def save_route(self, identity, conversation_id, message_id, proposal, decision) -> None: ...
    async def set_pending_intent(self, identity, conversation_id, message_id, candidate) -> dict: ...
    async def bind_task(self, identity, conversation_id, expected_revision, task_id) -> dict: ...
    async def finish_message(self, identity, conversation_id, message_id, result) -> dict: ...
    async def fail_message(self, identity, conversation_id, message_id, category) -> dict: ...
```

`reserve_message` must lock the conversation row, compare `expected_revision`, validate identical replay by text and payload, reject another pending message, insert the user message, and increment the conversation revision in the same transaction. Use `pg_try_advisory_lock(hashtextextended('conversation:' || id,0))` around the full external-model/workflow operation; release it in `finally`.

- [ ] **Step 5: Initialize the store in the application lifespan**

At `src/anlan/interfaces/api.py:91-98`, construct one `ConversationStore` and call `await conversations.initialize()` beside the existing store initializers. Do not expose endpoints yet.

- [ ] **Step 6: Run store and existing migration tests**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_store.py tests/test_postgres.py tests/test_service_reliability.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/infrastructure/conversations.py tests/test_conversation_store.py
```

Expected: all selected tests pass; the real PostgreSQL tests execute rather than skip.

- [ ] **Step 7: Commit the persistence slice**

```powershell
git add src/anlan/sql/013_conversations.sql src/anlan/infrastructure/conversations.py src/anlan/interfaces/api.py tests/test_conversation_store.py
git commit -m "feat: persist resumable conversations"
```

### Task 3: Add bounded classifier and chat model boundaries

**Files:**
- Create: `src/anlan/llm/conversation.py`
- Create: `src/anlan/sql/014_conversation_budget.sql`
- Modify: `src/anlan/infrastructure/budget.py:12-17,91-118`
- Modify: `src/anlan/interfaces/service_models.py:14-55`
- Test: `tests/test_conversation_model.py`
- Test: `tests/test_budget.py`

- [ ] **Step 1: Write failing scripted and provider-contract tests**

The scripted model must make deterministic tests possible without network access. The live model test must use `httpx.MockTransport` and a fake ledger:

```python
@pytest.mark.asyncio
async def test_scripted_classifier_separates_chat_candidate_and_confirmation():
    model = ScriptedConversationModel()
    assert (await model.classify(context("今天天气怎么样"))).intent == "casual_chat"
    candidate = await model.classify(context("明天在 V101 管线上补焊"))
    assert candidate.intent == "hot_work_candidate"
    assert candidate.requires_confirmation is True
    assert (await model.classify(context("确认申请", pending=True))).intent \
        == "confirm_pending_intent"


@pytest.mark.asyncio
async def test_live_classifier_rejects_unknown_intent_and_never_sends_identity():
    transport = RecordingTransport(model_response({
        "intent": "invented_tool_call", "fields": {},
        "requires_confirmation": False,
        "user_explanation": "x", "classifier_version": "ignored",
    }))
    model = live_model(transport)
    with pytest.raises(AnalysisFailure) as error:
        await model.classify(context("hello"))
    assert error.value.category == "invalid_output"
    request = transport.requests[0].json()
    serialized = json.dumps(request, ensure_ascii=False)
    assert "tenant_id" not in serialized and "user_id" not in serialized
```

Also verify: at most 12 recent visible messages, serialized context at most 16 KiB, no raw evidence or token, temperature zero, JSON response mode, 1024 output-token bound for classification, and no retry.

- [ ] **Step 2: Run the model tests and verify they fail**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_model.py -q
```

Expected: collection fails because `anlan.llm.conversation` does not exist.

- [ ] **Step 3: Implement protocols, scripted doubles, and DeepSeek adapters**

Define two interfaces and keep them tool-free:

```python
class IntentClassifier(Protocol):
    async def classify(self, context: ConversationContext) -> IntentProposal: ...


class ChatResponder(Protocol):
    async def respond(self, context: ConversationContext) -> AssistantReply: ...
```

`ConversationContext` contains only bounded visible messages, the conversation status, a sanitized task projection, and the current pending-intent candidate. It does not contain identity, credentials, database configuration, raw hidden traces, or write tools.

Use `ModelGateway` for both live calls so reservations happen before HTTP and failures remain sanitized. Use prompt versions `conversation-intent-v1` and `conversation-chat-v1`. The intent prompt requires exactly one `IntentProposal` JSON object; the chat prompt explicitly prohibits claiming that a task was created, updated, approved, or recovered.

- [ ] **Step 4: Add a distinct, non-resetting budget package**

Use `P11-WP01` for conversation model development. SQL014 only changes the package check constraint and migration record; it must not delete attempts, change authorization limits, or alter prior rows:

```sql
ALTER TABLE anlan_v2.model_budget_attempts
    DROP CONSTRAINT IF EXISTS model_budget_attempts_work_package_check;
ALTER TABLE anlan_v2.model_budget_attempts
    ADD CONSTRAINT model_budget_attempts_work_package_check
    CHECK (
        work_package ~ '^P[1-7]-WP[0-9]{2}$'
        OR work_package IN ('P8-WP03','P8-WP04','P11-WP01')
    );
INSERT INTO anlan_v2.anlan_schema_migrations(version) VALUES (14) ON CONFLICT DO NOTHING;
```

Add `CONVERSATION_WORK_PACKAGE = "P11-WP01"`, extend the Python validator, load SQL014 during ledger initialization, and add a test proving old attempts and limits are unchanged. Do not execute a real provider request in this task.

- [ ] **Step 5: Compose models without giving chat a workflow tool**

Add `ServiceModels.conversation()` as a factory that creates one classifier/responder pair per message operation: scripted implementations in `scripted_double` mode and a fresh bounded DeepSeek gateway pair in `deepseek_live` mode. The per-operation instances share the existing app-lifetime `httpx.AsyncClient` and durable `BudgetLedger`, but their in-memory request counters never leak across unrelated messages. Neither receives a `WorkflowService`, database connection, or `WorkflowAdapter`.

- [ ] **Step 6: Run contract and budget tests**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_model.py tests/test_budget.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/llm/conversation.py src/anlan/infrastructure/budget.py src/anlan/interfaces/service_models.py tests/test_conversation_model.py tests/test_budget.py
```

Expected: all selected tests pass with mock transports and no real model request.

- [ ] **Step 7: Commit model boundaries separately**

```powershell
git add src/anlan/llm/conversation.py src/anlan/sql/014_conversation_budget.sql src/anlan/infrastructure/budget.py src/anlan/interfaces/service_models.py tests/test_conversation_model.py tests/test_budget.py
git commit -m "feat: add bounded conversation models"
```

### Task 4: Adapt the existing material workflow and build the sidebar projection

**Files:**
- Create: `src/anlan/interfaces/conversation_runtime.py`
- Test: `tests/test_conversation_runtime.py`

- [ ] **Step 1: Write failing adapter tests around a fake material service**

Prove exact mappings and deterministic request IDs:

```python
@pytest.mark.asyncio
async def test_start_maps_confirmed_fields_and_uses_message_scoped_request_id():
    material = FakeMaterialService(start_result=waiting_task())
    adapter = WorkflowAdapter(lambda: fake_context(material))
    result = await adapter.start(
        OWNER, "conv-1", "message-1",
        {"work_object_description": "V101 管线补焊"},
    )
    assert material.start_calls == [(
        OWNER,
        {
            "work_location_description": "",
            "work_object_description": "V101 管线补焊",
            "work_method_description": "",
            "attachment_description": "",
        },
        "conversation:conv-1:message-1:start",
    )]
    assert result.projection.status == "waiting_input"
    assert result.projection.missing_fields == [
        "work_location_description", "work_method_description", "attachment_description"
    ]
```

Add tests for `resume` only in `waiting_input`, `revise` only in `awaiting_review`, stale revision propagation, recover, task not found, and projection of issues, analysis mode, semantic status, events/reviews summary, and stale review warnings.

- [ ] **Step 2: Run the adapter tests and verify they fail**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_runtime.py -q
```

Expected: collection fails because `conversation_runtime.py` does not exist.

- [ ] **Step 3: Implement the adapter as the sole workflow-writing boundary**

Use an injected async context-manager factory so production uses `models.material_service()` and unit tests use a fake. Expose only:

```python
class WorkflowAdapter:
    async def start(self, identity, conversation_id, message_id, fields) -> WorkflowResult: ...
    async def submit(
        self, identity, conversation_id, message_id, task_id,
        expected_revision, fields, status,
    ) -> WorkflowResult: ...
    async def recover(self, identity, task_id) -> WorkflowResult: ...
    async def read(self, identity, task_id) -> WorkflowResult: ...
```

The adapter creates a complete `Application` with empty defaults before `start`, chooses `resume` versus `revise` from the freshly read task status, and derives stable request IDs from conversation ID, message ID, and action. It never approves a task, changes an alarm, or writes directly to workflow tables.

- [ ] **Step 4: Build a bounded `TaskProjection`**

The projection contains task ID, status, revision, acquired/missing fields, issue questions, analysis mode, semantic status, recoverability, and summarized event/review counts. It excludes raw model responses, credentials, full traces, and hidden reasoning. Validate it with Pydantic before returning it to the conversation or browser.

- [ ] **Step 5: Run adapter and material regressions**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_runtime.py tests/test_service_reliability.py tests/test_material_revisions.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/interfaces/conversation_runtime.py tests/test_conversation_runtime.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the workflow adapter slice**

```powershell
git add src/anlan/interfaces/conversation_runtime.py tests/test_conversation_runtime.py
git commit -m "feat: adapt material workflow for conversation"
```

### Task 5: Orchestrate one message with idempotency and crash recovery

**Files:**
- Create: `src/anlan/conversation/service.py`
- Test: `tests/test_conversation_service.py`
- Test: `tests/test_conversation_recovery.py`

- [ ] **Step 1: Write failing end-to-end service tests using scripted collaborators**

Test the approved paths at service level:

```python
@pytest.mark.asyncio
async def test_candidate_then_confirmation_creates_exactly_one_task(service):
    conversation = await service.create(OWNER, request_id="create")
    candidate = await service.message(
        OWNER, conversation["conversation_id"],
        request_id="m1", expected_revision=1,
        text="明天在一号罐区 V101 管线上补焊",
    )
    assert candidate["status"] == "pending_confirmation"
    assert candidate["task_projection"] is None
    assert service.workflow.start_calls == []

    started = await service.message(
        OWNER, conversation["conversation_id"],
        request_id="m2", expected_revision=candidate["revision"], text="确认申请",
    )
    assert started["status"] == "active_hot_work"
    assert len(service.workflow.start_calls) == 1
    assert started["task_projection"]["task_id"]


@pytest.mark.asyncio
async def test_chat_during_active_task_never_calls_workflow(service_with_active_task):
    before = service_with_active_task.workflow.calls.copy()
    result = await service_with_active_task.send("电焊和气焊有什么区别？")
    assert result["status"] == "active_hot_work"
    assert service_with_active_task.workflow.calls == before
    assert "当前动火任务" in result["messages"][-1]["text"]
```

Also cover pending-intent rejection, amendment and reconfirmation; unambiguous task input; ambiguous input requiring confirmation; pause/resume; cancellation that only detaches the conversation; new task choice; classifier failure; chat failure; changed replay; stale revision; and a second pending message.

- [ ] **Step 2: Add crash-window tests before implementation**

Inject failures at three points:

1. after user-message reservation but before classification;
2. after route persistence but before workflow call;
3. after material task creation but before conversation binding.

For case 3, retrying the same message must derive the same material `request_id`, recover the same task, and bind it once. The test must assert one material task and one model proposal, not merely equal response text.

- [ ] **Step 3: Run service tests and verify they fail**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_service.py tests/test_conversation_recovery.py -q
```

Expected: collection fails because `ConversationService` does not exist.

- [ ] **Step 4: Implement the message orchestration sequence**

Implement this exact ordering:

```python
async def message(self, identity, conversation_id, payload):
    reservation = await self.store.reserve_message(
        identity, conversation_id, payload.request_id,
        payload.expected_revision, payload.text,
    )
    if reservation.get("result") is not None:
        return reservation["result"]
    async with self.store.operation_lock(identity, conversation_id, reservation["message_id"]):
        state = await self.snapshot(identity, conversation_id)
        proposal = await self.classifier.classify(self.context(state, payload.text))
        decision = decide(state, proposal)
        await self.store.save_route(
            identity, conversation_id, reservation["message_id"],
            proposal.model_dump(), decision.model_dump(),
        )
        result = await self.execute(identity, state, reservation, proposal, decision)
        return await self.store.finish_message(
            identity, conversation_id, reservation["message_id"], result,
        )
```

`execute()` may call the chat responder or workflow adapter only as allowed by `RouteDecision`. It must build all assistant text from validated results, not from claimed model side effects. Failures are stored as sanitized categories. A retry resumes from the persisted route/action rather than classifying again when the route already exists.

- [ ] **Step 5: Implement snapshot assembly and sidebar refresh**

Every returned snapshot includes ordered visible messages, conversation revision/status, pending confirmation card, active task projection, and allowed UI actions. If reading the active task reports a stale or missing binding, preserve the conversation and return a visible recovery/error state; do not silently detach it.

- [ ] **Step 6: Run service, recovery, policy, and store tests**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_policy.py tests/test_conversation_store.py tests/test_conversation_service.py tests/test_conversation_recovery.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/conversation src/anlan/infrastructure/conversations.py tests/test_conversation_*.py
```

Expected: all selected tests pass, including real PostgreSQL recovery tests.

- [ ] **Step 7: Commit the orchestrator slice**

```powershell
git add src/anlan/conversation/service.py tests/test_conversation_service.py tests/test_conversation_recovery.py
git commit -m "feat: orchestrate resumable conversation messages"
```

### Task 6: Expose authenticated conversation HTTP and SSE APIs

**Files:**
- Create: `src/anlan/interfaces/conversation_routes.py`
- Modify: `src/anlan/interfaces/api.py:80-99,287-289`
- Test: `tests/test_conversation_api.py`
- Modify: `tests/test_service_http.py`

- [ ] **Step 1: Write failing API tests**

Use `httpx.ASGITransport` to verify authentication, body validation, idempotency, tenant isolation, error mapping, and task projection:

```python
conversation = await client.post(
    "/conversations", headers=headers,
    json={"request_id": "create-conversation"},
)
assert conversation.status_code == 200
conversation_id = conversation.json()["conversation_id"]

candidate = await client.post(
    f"/conversations/{conversation_id}/messages", headers=headers,
    json={
        "request_id": "message-1", "expected_revision": 1,
        "text": "明天在一号罐区 V101 管线上补焊",
    },
)
assert candidate.json()["status"] == "pending_confirmation"
assert candidate.json()["task_projection"] is None
assert (await client.get(f"/conversations/{conversation_id}", headers=other_headers)) \
    .status_code == 404
```

Add list and snapshot tests, 32 KiB body enforcement, maximum 8 KiB message enforcement, missing/invalid `Last-Event-ID`, and 409 on stale revision or active processing.

- [ ] **Step 2: Run API tests and verify route failures**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_api.py -q
```

Expected: requests return 404 because conversation routes are not installed.

- [ ] **Step 3: Add strict request contracts and routes**

Define `CreateConversationRequest` and `ConversationMessageRequest` using `Identifier`, strict bounded text, and `expected_revision >= 1`. Install:

```python
@app.post("/conversations")
async def create_conversation(payload: CreateConversationRequest, identity: Actor): ...

@app.get("/conversations")
async def list_conversations(identity: Actor): ...

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, identity: Actor): ...

@app.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str, payload: ConversationMessageRequest, identity: Actor,
): ...

@app.get("/conversations/{conversation_id}/stream")
async def stream_conversation(...): ...
```

Reuse `snapshot_stream`; this is a latest-snapshot semantic stream, not a token stream or lossless queue. Validate `Last-Event-ID` exactly as existing task/event/review streams do.

- [ ] **Step 4: Compose the service in `create_app`**

Create one store and workflow adapter inside app construction, and give `ConversationService` a per-message model factory from `ServiceModels.conversation()`. Pass the authenticated dependency and service to `install_conversation_routes`. Do not create one live gateway at app startup because `ModelGateway.requests_used` is operation-local. Do not add conversation actions to the general `/{resource}/{key}/stream` route; keep the explicit path to avoid ambiguous resource handling.

- [ ] **Step 5: Extend real HTTP restart and SSE tests**

In `tests/test_service_http.py`, create a conversation, submit a candidate, read its SSE snapshot, restart the owned server, confirm the candidate, and verify that the same conversation now binds one persisted material task. Closing the SSE connection must not cancel a message or workflow.

- [ ] **Step 6: Run API and real HTTP tests**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_api.py tests/test_service_api.py tests/test_service_http.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/interfaces/conversation_routes.py src/anlan/interfaces/api.py tests/test_conversation_api.py tests/test_service_http.py
```

Expected: all selected tests pass with real PostgreSQL and the scripted conversation model.

- [ ] **Step 7: Commit the transport slice**

```powershell
git add src/anlan/interfaces/conversation_routes.py src/anlan/interfaces/api.py tests/test_conversation_api.py tests/test_service_http.py
git commit -m "feat: expose conversation api and stream"
```

### Task 7: Replace the form-first console with chat and a task sidebar

**Files:**
- Modify: `src/anlan/interfaces/console/assets/index.html:1-104`
- Modify: `src/anlan/interfaces/console/assets/app.js:1-247`
- Modify: `src/anlan/interfaces/console/assets/api.js:1-57`
- Modify: `src/anlan/interfaces/console/assets/styles.css:1-812`
- Modify: `src/anlan/interfaces/console/routes.py:35-84`
- Test: `tests/test_console.py`
- Test: `tests/test_console_live.py`

- [ ] **Step 1: Change static-console tests before changing assets**

Assert the new semantic shell and removal of the primary material form:

```python
shell = await client.get("/console")
assert 'id="conversation-list"' in shell.text
assert 'id="message-list"' in shell.text
assert 'id="message-composer"' in shell.text
assert 'id="task-sidebar"' in shell.text
assert 'id="material-form"' not in shell.text
assert 'aria-live="polite"' in shell.text
```

Update the console integration scenario to create a conversation through the same API the browser uses, submit a candidate, confirm it, supplement one missing field, and verify the returned sidebar projection. Keep existing event simulation, review, and feedback routes tested and accessible from the active-task sidebar/details.

- [ ] **Step 2: Run console tests and verify they fail against the old form UI**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_console.py tests/test_console_live.py -q
```

Expected: new shell assertions fail because the existing HTML still contains `material-form` and lacks chat elements.

- [ ] **Step 3: Implement the approved desktop and mobile structure**

Use one main chat column and one task sidebar:

```html
<section class="conversation-shell" id="conversation-shell">
  <div class="chat-column">
    <ol id="message-list" class="message-list" aria-live="polite"></ol>
    <form id="message-composer" class="message-composer">
      <label class="sr-only" for="message-input">给安澜发送消息</label>
      <textarea id="message-input" maxlength="8000" required></textarea>
      <button class="primary" type="submit">发送</button>
    </form>
  </div>
  <aside id="task-sidebar" class="task-sidebar" aria-label="当前任务"></aside>
</section>
```

The left navigation lists conversations, not material tasks. Desktop keeps the task sidebar visible; below 660 px it becomes an accessible disclosure above the composer. Preserve the connection/token flow and the explicit SYNTHETIC and no-approval notices.

- [ ] **Step 4: Replace browser state and rendering logic**

`app.js` should keep only connection state, the selected conversation snapshot, busy state, and stream handle. Implement focused render functions:

```javascript
function renderMessages(snapshot) { /* visible messages and confirmation cards */ }
function renderTaskProjection(snapshot) { /* status, revision, fields, issues, evidence */ }
function renderConversationList(items) { /* recent conversations */ }
async function sendMessage(text) { /* mutate one conversation endpoint */ }
function subscribe(conversationId) { /* latest-snapshot SSE with Last-Event-ID */ }
```

Confirmation card buttons send explicit visible messages such as `确认申请` and `不是，继续聊`; they do not call `/tasks` directly. Enter sends, Shift+Enter inserts a newline, busy state prevents duplicate clicks, and failures preserve draft text until the server state is refreshed.

- [ ] **Step 5: Keep event/review functions behind the task details**

Move current event simulation, event selection, review, evidence, and feedback controls into a collapsible section of the task sidebar. They continue to call the existing authenticated event/review endpoints and retain the original warning that raw alarms remain independent. Do not make event simulation part of free-form chat in this feature.

- [ ] **Step 6: Update `api.js` for conversation idempotency and streams**

Keep request IDs in memory until a definitive response, as today. Add a small `subscribeSnapshot(path, handlers)` wrapper around `EventSource` only if authenticated headers can be sent safely; because native `EventSource` cannot set bearer headers, prefer the existing authorized `fetch()` readable-stream pattern. Never put the bearer token in the URL, localStorage, logs, or HTML.

- [ ] **Step 7: Run console tests and inspect responsive layout**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_console.py tests/test_console_live.py -q
.venv/Scripts/python.exe -m ruff check src/anlan/interfaces/console src/anlan/interfaces/conversation_routes.py
```

Then start the scripted service and inspect `/console` at approximately 1440×900 and 390×844. Verify keyboard focus, long Chinese messages, pending confirmation, waiting-input sidebar, sidebar disclosure, refresh recovery, and event/review details. Save screenshots and a sanitized result under a new `docs/phases/` evidence directory chosen for this feature; do not overwrite P8 evidence.

Expected: tests pass; no horizontal overflow or clipped composer; token remains only in page memory.

- [ ] **Step 8: Commit the conversation console**

```powershell
git add src/anlan/interfaces/console tests/test_console.py tests/test_console_live.py
git commit -m "feat: replace console form with conversation ui"
```

### Task 8: Add routing evaluation and safety regression gates

**Files:**
- Create: `evals/conversation-routing-v1/README.md`
- Create: `evals/conversation-routing-v1/cases.json`
- Create: `evals/evaluate_conversation_routing.py`
- Create: `tests/test_conversation_evaluation.py`
- Create: `scripts/smoke_conversation.py`
- Test: `tests/test_phase_gate.py`

- [x] **Step 1: Write the failing evaluator tests**

The scorer must separate routing quality from control-flow safety:

```python
def test_score_reports_false_activation_and_confirmation_separately():
    report = score([
        outcome("chat-1", expected="casual_chat", predicted="hot_work_candidate",
                confirmation_requested=True, business_writes=0),
        outcome("hot-1", expected="hot_work_candidate", predicted="hot_work_candidate",
                confirmation_requested=True, business_writes=0),
    ])
    assert report["routing"]["chat_false_positive"] == 1
    assert report["safety"]["unconfirmed_business_writes"] == 0
```

Also test per-slice counts, malformed results, duplicate IDs, empty slices, field-extraction exact match, and deterministic JSON ordering.

- [x] **Step 2: Run evaluator tests and verify they fail**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_evaluation.py -q
```

Expected: import fails because the evaluator does not exist.

- [x] **Step 3: Create a versioned initial dataset**

Start with at least 40 reviewed SYNTHETIC cases split across:

- ordinary chat and greetings;
- explicit and implicit hot-work requests;
- negation, quotation, hypothetical questions, and knowledge consultation;
- active-task field supplements and ambiguous statements;
- pause, resume, task switch, and new-task requests;
- prompt injection and requests to bypass confirmation;
- welding/repair descriptions that are not applications.

Each case includes `case_id`, `slice`, `conversation_state`, visible history, input, expected intent, expected fields, whether confirmation is required, and maximum allowed business writes. Freeze case IDs and document that the set is a development baseline, not production accuracy proof.

- [x] **Step 4: Implement the offline evaluator and smoke script**

The evaluator consumes saved proposals/results and never calls the provider by default. Report intent confusion counts, hot-work recall, chat false positives, confirmation coverage, field exact match, and unconfirmed business writes. `scripts/smoke_conversation.py` runs the scripted API sequence across process boundaries and writes to a new output path only.

- [x] **Step 5: Add safety gates to the phase regression**

Extend `tests/test_phase_gate.py` so a release fails when scripted scenarios create a task before confirmation, mutate a task during chat, lose the active task after refresh, or produce any unconfirmed business write. Do not set an arbitrary live-model quality threshold from the initial 40 development cases.

- [x] **Step 6: Run the evaluation and smoke tests**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_conversation_evaluation.py tests/test_phase_gate.py -q
.venv/Scripts/python.exe evals/evaluate_conversation_routing.py --input evals/conversation-routing-v1/scripted-results.json --output .runtime/conversation-routing-check.json
.venv/Scripts/python.exe scripts/smoke_conversation.py --output .runtime/conversation-smoke-check.json
```

Expected: tests pass; both commands create new reports; scripted safety count `unconfirmed_business_writes` is zero. The report must label scripted routing separately from any live model result.

- [x] **Step 7: Commit evaluation assets**

```powershell
git add evals/conversation-routing-v1 evals/evaluate_conversation_routing.py scripts/smoke_conversation.py tests/test_conversation_evaluation.py tests/test_phase_gate.py
git commit -m "test: add conversation routing safety gate"
```

### Task 9: Run the full gate, document boundaries, and prepare live validation separately

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`
- Modify: `docs/capability-matrix.md`
- Create: `docs/phases/phase-11-conversation/acceptance.md`
- Create: `docs/phases/phase-11-conversation/handoff.md`
- Create: `docs/phases/phase-11-conversation/evidence/gate-report.md`

- [x] **Step 1: Update documentation from actual behavior only**

Document the conversation start command, scripted demonstration, chat/task boundary, second confirmation, persistence, task sidebar, SSE semantics, model-budget package, and known limitations. State explicitly that:

- the console remains SYNTHETIC and does not approve work;
- scripted routing proves control flow, not model quality;
- chat can fail independently without changing the task;
- the live conversation package has not been exercised unless a separately authorized report exists;
- existing P9 and P10 plans remain independent and incomplete.

- [x] **Step 2: Run focused tests with real PostgreSQL**

Run:

```powershell
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
.venv/Scripts/python.exe -m pytest tests/test_conversation_policy.py tests/test_conversation_store.py tests/test_conversation_model.py tests/test_conversation_runtime.py tests/test_conversation_service.py tests/test_conversation_recovery.py tests/test_conversation_api.py tests/test_console.py tests/test_console_live.py tests/test_conversation_evaluation.py -q
```

Expected: all selected tests pass, PostgreSQL-marked tests execute, and no network model call occurs.

- [x] **Step 3: Run the full application gate**

Run:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests evals scripts
```

Expected: all executed tests pass and Ruff reports no diagnostics. Report any environmental skips separately; do not count them as passing.

- [x] **Step 4: Run package and clean-start checks**

Build a wheel, inspect that SQL013/SQL014 and console assets are included, install it into an isolated environment, start the scripted service against the test database, and run `scripts/smoke_conversation.py` outside the source tree. Confirm process restart recovery and that the budget snapshot is unchanged by scripted validation.

- [x] **Step 5: Perform the browser acceptance path**

In the actual browser, execute:

> “明天去罐区补焊” → second confirmation → task creation → missing-field question → natural-language supplement → temporary chat question → return to task → refresh → same task and revision.

Also verify rejection, pause/resume, stale revision, mobile layout, and event/review details. Record screenshots and a sanitized report. Never include the bearer token, model key, DSN, raw private configuration, or hidden model output.

- [ ] **Step 6: Deferred live-provider budget decision**

Read the cloud ledger snapshot and report the shared remaining total plus `P8-WP04` remaining count. Request explicit user confirmation for using the new `P11-WP01` package and state the proposed maximum number of calls for a minimal validation. Without that confirmation, finish the engineering gate as scripted-only and mark live intent/chat quality unverified.

Actual: deferred as a whole. No cloud credential access or cloud-ledger read was performed in these implementation batches. Local scripted engineering verification is complete independently; the frozen local 46/100 count must not be used as cloud remaining-budget evidence.

- [ ] **Step 7: If separately authorized, run a minimal live evaluation**

Use reviewed SYNTHETIC cases only. Reserve each call before HTTP, perform no automatic retries, preserve failures, and compare the live proposals against the frozen dataset. A valid minimum is one explicit hot-work candidate, one ordinary chat case, one ambiguous/non-application case, plus any required chat-response calls within the user-approved maximum. Do not claim production accuracy from this sample.

- [x] **Step 8: Record final evidence and commit only feature-owned paths**

```powershell
git add README.md docs/architecture.md docs/capability-matrix.md docs/phases/phase-11-conversation
git add -p docs/status.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: record conversation interface verification"
```

When interactively staging `docs/status.md`, select only the new conversation-status hunk and reject the user's pre-existing P10/status edits. Before committing, inspect the cached diff, not only the filename list. The final handoff must list exact test results, skips, live-call count or absence, budget before/after, deployment status, and remaining limitations.

---

## Plan completion gate

Before calling the implementation complete, verify all of the following from fresh output:

- the approved chat + task-sidebar path works through the conversation API;
- no material task exists before explicit confirmation;
- casual chat and failed chat responses cause zero business writes;
- duplicate and crash-recovery paths produce one task and one durable result;
- restart restores messages, pending intent, active task, and task revision;
- event/review functionality remains reachable and alarms remain independent;
- routing evaluation reports zero unconfirmed business writes;
- selected and full tests pass with environmental skips disclosed;
- the model budget ledger does not change during scripted verification;
- live-model results are absent or separately authorized and reported without exaggeration.
