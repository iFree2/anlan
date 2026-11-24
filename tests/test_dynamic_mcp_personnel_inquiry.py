"""Workflow boundary checks; SDK transport integration is tested separately."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import AwareDatetime

from anlan.common.models import Identity, StrictModel
from anlan.infrastructure.trace import JsonlTrace
from anlan.llm.tool_model import FinalAnswer, ModelTurn, ToolCall
from anlan.tools.dynamic_mcp.contracts import CapabilityRequest
from anlan.tools.registry import ToolDefinition, ToolRegistry

CAPS = ("contractor.qualification.query", "person.training.query", "person.access.query")
NOW = datetime(2026, 11, 17, tzinfo=UTC)
IDENTITY = Identity(tenant_id="T", user_id="U")


class Observation(StrictModel):
    tool: str
    object_id: None = None
    queried_at: AwareDatetime
    outcome: str = "unknown"
    reason: str | None = "missing"
    facts: None = None
    source: None = None
    evidence: dict | None = None
    complete: bool = False
    required_capability: str


class SequenceModel:
    mode = "scripted_double"

    def __init__(self, turns):
        self.turns = iter(turns)
        self.catalog = None

    def bind_catalog(self, catalog):
        self.catalog = catalog
        return self

    async def next(self, messages, run_id):
        return next(self.turns)


@pytest.fixture
def boundary(monkeypatch):
    import importlib.util

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module

    entries = tuple(
        SimpleNamespace(
            alias=f"alias_{i}",
            capability=cap,
            service_id="svc",
            original_name=f"equipment.tool.{i}",
            generation=1,
            config_revision=1,
            discovery_id="discovery",
        )
        for i, cap in enumerate(CAPS)
    )
    requests = tuple(
        (
            e.alias,
            CapabilityRequest(
                capability=e.capability,
                factory_id="F",
                objects=["C" if e.capability == CAPS[0] else "P"],
                queried_at=NOW,
                category="hot-work"
                if e.capability == CAPS[0]
                else "safety"
                if e.capability == CAPS[1]
                else None,
            ).model_dump_json(),
        )
        for e in entries
    )
    from anlan.tools.policy import FrozenTaskGrant

    snapshot = SimpleNamespace(
        identity=IDENTITY,
        query_at=NOW,
        entries=entries,
        requests=requests,
        task_grant=FrozenTaskGrant(IDENTITY, requests),
        task_id="task",
        run_id="run",
        correlation_id="corr",
        revision=1,
        policy_version="p1",
        directory_version="d1",
        catalog_id="catalog",
        factory_id="F",
        contractor_id="C",
        person_id="P",
        qualification_category="hot-work",
        training_category="safety",
        required_capabilities=CAPS,
    )
    state = SimpleNamespace(wire=[], snapshot=snapshot, delay=0, evidence=True)

    async def prepare(*args, **kwargs):
        return snapshot

    def build(snap, host, budget):
        definitions = []
        for entry in entries:

            async def handler(identity, params, entry=entry):
                budget.reserve_wire_call()
                state.wire.append(entry.alias)
                if state.delay:
                    await asyncio.sleep(state.delay)
                return Observation(
                    tool=entry.alias,
                    queried_at=NOW,
                    required_capability=entry.capability,
                    evidence={
                        "remote": {
                            "outcome": "unknown",
                            "complete": False,
                            "reason": "missing",
                            "data": [],
                            "next_cursor": None,
                            "sources": [],
                        },
                        "host": {"call_id": f"receipt_{len(state.wire)}"},
                    }
                    if state.evidence
                    else None,
                )

            definitions.append(
                ToolDefinition(
                    entry.alias,
                    "safe local capability",
                    CapabilityRequest,
                    Observation,
                    handler,
                    lambda: NOW,
                )
            )
        return ToolRegistry(definitions)

    monkeypatch.setattr(module, "prepare_personnel", prepare)
    monkeypatch.setattr(module, "build_dynamic_definitions", build)
    state.run = lambda model, **kw: module.check_external_personnel(
        None,
        IDENTITY,
        SimpleNamespace(question="设备情况"),
        None,
        None,
        None,
        model,
        JsonlTrace(),
        **kw,
    )
    return state


def call(boundary, ident, index=0, arguments=None):
    alias, params = boundary.snapshot.requests[index]
    return ToolCall(id=ident, name=alias, arguments=params if arguments is None else arguments)


async def test_repeat_across_rounds_stops_before_executor(boundary):
    turn = ModelTurn(calls=[call(boundary, "same")])
    result = await boundary.run(SequenceModel([turn, turn]))
    assert result["stop_reason"] == "duplicate_call_id"
    assert result["attempts"] == result["wire_calls"] == 1
    assert boundary.wire == ["alias_0"]


@pytest.mark.parametrize("invalid", [False, True])
async def test_seventh_attempt_never_reaches_executor(boundary, invalid):
    calls = [call(boundary, f"call_{i}", arguments="{}" if invalid else None) for i in range(7)]
    result = await boundary.run(
        SequenceModel([ModelTurn(calls=calls[:4]), ModelTurn(calls=calls[4:])])
    )
    assert result["stop_reason"] == "tool_budget_exhausted"
    assert result["attempts"] == 6
    assert result["wire_calls"] == (0 if invalid else 6)
    assert len(result["attempt_ledger"]) == 6


async def test_scripted_bound_catalog_keeps_unknown_partial_and_no_shared_schemas(boundary):
    from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel

    model = ScriptedDynamicToolModel()
    result = await boundary.run(model)
    assert result["schema_version"] == "dynamic-inquiry-evidence-v1"
    assert result["stop_reason"] == "completed"
    assert result["required_capabilities"] == result["observed_capabilities"] == list(CAPS)
    assert result["missing_capabilities"] == []
    assert result["partial_capabilities"] == list(CAPS)
    assert result["unknown_capabilities"] == list(CAPS)
    assert result["summary"]["evidence_call_ids"] == [r["call_id"] for r in result["results"]]
    assert result["attempts"] == result["wire_calls"] == 3
    assert result["model_steps"] == 2
    assert model.catalog is None


async def test_forged_citation_rejected(boundary):
    calls = [call(boundary, f"call_{i}", i) for i in range(3)]
    result = await boundary.run(
        SequenceModel(
            [
                ModelTurn(calls=calls),
                ModelTurn(final=FinalAnswer(summary="candidate", evidence_call_ids=["other_run"])),
            ]
        )
    )
    assert result["stop_reason"] == "unsupported_citation"
    assert result["summary"] is None


async def test_no_received_evidence_is_not_citable(boundary):
    boundary.evidence = False
    result = await boundary.run(
        SequenceModel(
            [
                ModelTurn(calls=[call(boundary, "call_0")]),
                ModelTurn(final=FinalAnswer(summary="candidate", evidence_call_ids=["call_0"])),
            ]
        )
    )
    assert result["stop_reason"] == "unsupported_citation"
    assert result["results"][0]["evidence_valid"] is False
    assert result["missing_capabilities"] == list(CAPS)


async def test_parent_timeout_stops_execution(boundary):
    from anlan.workflows.external_inquiry_personnel import InquiryLimits

    boundary.delay = 0.2
    result = await boundary.run(
        SequenceModel([ModelTurn(calls=[call(boundary, "slow")])]),
        limits=InquiryLimits(timeout_seconds=0.02),
    )
    assert result["stop_reason"] == "loop_timeout"
    assert result["attempts"] == result["wire_calls"] == 1
    assert result["attempt_ledger"][0]["status"] == "cancelled"


def test_limits_cannot_raise_frozen_ceilings():
    from anlan.workflows.external_inquiry_personnel import InquiryLimits

    for kwargs in (
        {"max_attempts": 7},
        {"max_wire_calls": 7},
        {"max_model_steps": 4},
        {"timeout_seconds": 61},
    ):
        with pytest.raises(ValueError):
            InquiryLimits(**kwargs)


async def test_host_query_clock_is_passed_to_preparation(boundary, monkeypatch):
    import importlib.util

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module

    seen = []

    async def prepare(*args):
        seen.append(args[-1])
        return boundary.snapshot

    monkeypatch.setattr(module, "prepare_personnel", prepare)
    await boundary.run(
        SequenceModel([ModelTurn(final=FinalAnswer(summary="unknown", evidence_call_ids=[]))]),
        query_at=NOW,
    )
    assert seen == [NOW]


async def test_duplicate_inside_batch_rejects_whole_batch(boundary):
    result = await boundary.run(
        SequenceModel(
            [ModelTurn(calls=[call(boundary, "duplicate", 0), call(boundary, "duplicate", 1)])]
        )
    )
    assert result["stop_reason"] == "duplicate_call_id"
    assert result["attempts"] == result["wire_calls"] == 0
    assert boundary.wire == []


async def test_scripted_views_have_independent_schema_data():
    from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel
    from anlan.tools.policy import TaskCatalog

    catalog = TaskCatalog(IDENTITY, (), ())
    original = ScriptedDynamicToolModel()
    a, b = original.bind_catalog(catalog), original.bind_catalog(catalog)
    a.tool_schemas.append({"changed": True})
    assert a.catalog is b.catalog is catalog
    assert b.tool_schemas == original.tool_schemas == []


async def test_action_receipt_links_and_uncertainty_warnings(boundary):
    from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel

    result = await boundary.run(ScriptedDynamicToolModel())
    assert result["summary_status"] == "unverified_candidate"
    assert result["evidence_warnings"]
    assert {w["capability"] for w in result["evidence_warnings"]} == set(CAPS)
    for observation, attempt in zip(result["results"], result["attempt_ledger"]):
        assert observation["action_call_id"] == observation["call_id"]
        assert observation["receipt_call_id"] == observation["evidence"]["host"]["call_id"]
        assert attempt["receipt_call_id"] == observation["receipt_call_id"]


async def test_missing_sources_are_visible_even_if_remote_claims_complete_ok(boundary, monkeypatch):
    # The Executor-bound boundary still returns a correctly typed observation;
    # source quality must stay distinct from request binding and publication.
    import importlib.util

    from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module

    real_executor = module.ToolExecutor

    class UnsourcedExecutor(real_executor):
        async def execute(self, *args):
            value = await super().execute(*args)
            value.update(outcome="ok", reason=None, complete=True)
            value["evidence"]["remote"].update(outcome="ok", complete=True)
            return value

    monkeypatch.setattr(module, "ToolExecutor", UnsourcedExecutor)
    result = await boundary.run(ScriptedDynamicToolModel())
    assert {
        w["capability"] for w in result["evidence_warnings"] if w["kind"] == "source_unavailable"
    } == set(CAPS)
    assert "sources=unavailable" in result["summary"]["summary"]


async def test_budget_deadline_rejection_becomes_timeout_report(boundary, monkeypatch):
    import importlib.util

    from anlan.tools.dynamic_mcp.runtime import RuntimeFailure

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module

    base = module.CallBudget

    class ExpiredAtReservation(base):
        def reserve_attempt(self, call_id=None):
            raise RuntimeFailure("timeout")

    monkeypatch.setattr(module, "CallBudget", ExpiredAtReservation)
    result = await boundary.run(SequenceModel([ModelTurn(calls=[call(boundary, "late")])]))
    assert result["stop_reason"] == "loop_timeout"
    assert result["attempts"] == result["wire_calls"] == 0


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("missing_sources", "missing_sources"),
        ("expired_source", "source_outside_validity"),
        ("future_source", "source_from_future"),
        ("missing_validity", "source_validity_missing"),
        ("missing_version", "source_version_missing"),
        ("missing_updated_at", "source_updated_at_missing"),
        ("valid", None),
    ],
)
async def test_m1_usability_is_distinct_from_valid_observation(
    boundary, monkeypatch, condition, reason
):
    import importlib.util
    from datetime import timedelta

    from anlan.llm.dynamic_tool_model import ScriptedDynamicToolModel
    from anlan.tools.dynamic_mcp.contracts import DynamicEvidence

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module

    source = dict(
        system_id="system",
        record_id=None,
        version="1",
        updated_at=NOW,
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
    )
    if condition == "expired_source":
        source["valid_until"] = NOW
    elif condition == "future_source":
        source["updated_at"] = NOW + timedelta(seconds=1)
    elif condition == "missing_validity":
        source.update(valid_from=None, valid_until=None)
    elif condition == "missing_version":
        source["version"] = None
    elif condition == "missing_updated_at":
        source["updated_at"] = None
    base = module.ToolExecutor

    class EvidenceExecutor(base):
        async def execute(self, *args):
            value = await super().execute(*args)
            remote = DynamicEvidence(
                schema_version="dynamic-evidence-v1",
                capability=value["required_capability"],
                contract_version="1",
                data_origin="SYNTHETIC",
                factory_id="F",
                objects=["E"],
                queried_at=NOW,
                outcome="ok",
                reason=None,
                data=[],
                sources=[] if condition == "missing_sources" else [source],
                complete=True,
                next_cursor=None,
                coverage=dict(object_ids=["E"], start=None, end=None),
            )
            assert remote.usable == (condition == "valid")
            value.update(outcome="ok", reason=None, complete=True)
            value["evidence"]["remote"] = remote.model_dump(mode="json")
            return value

    monkeypatch.setattr(module, "ToolExecutor", EvidenceExecutor)
    result = await boundary.run(ScriptedDynamicToolModel())
    assert result["observed_capabilities"] == list(CAPS)
    assert result["missing_capabilities"] == []
    assert all(r["evidence_valid"] for r in result["results"])
    assert result["unusable_capabilities"] == ([] if condition == "valid" else list(CAPS))
    assert result["unknown_capabilities"] == ([] if condition == "valid" else list(CAPS))
    for observation in result["results"]:
        assert observation["usable"] == (condition == "valid")
        assert observation["usability_reason"] == reason


async def test_dynamic_candidate_cannot_smuggle_knowledge_citations(boundary):
    from anlan.knowledge.contracts import KnowledgeCitation

    result = await boundary.run(
        SequenceModel(
            [
                ModelTurn(calls=[call(boundary, f"call_{i}", i) for i in range(3)]),
                ModelTurn(
                    final=FinalAnswer(
                        summary="candidate",
                        evidence_call_ids=["call_0"],
                        knowledge_citations=[
                            KnowledgeCitation(chunk_id="invented", quote="never returned")
                        ],
                    )
                ),
            ]
        )
    )
    assert result["stop_reason"] == "unsupported_knowledge_citation"
    assert result["summary"] is None


async def test_synchronous_model_overrun_cannot_publish_candidate(boundary):
    from time import sleep

    from anlan.workflows.external_inquiry_personnel import InquiryLimits

    class BlockingFinal(SequenceModel):
        async def next(self, messages, run_id):
            turn = await super().next(messages, run_id)
            if turn.final is not None:
                sleep(0.04)
            return turn

    result = await boundary.run(
        BlockingFinal(
            [
                ModelTurn(calls=[call(boundary, f"call_{i}", i) for i in range(3)]),
                ModelTurn(final=FinalAnswer(summary="candidate", evidence_call_ids=["call_0"])),
            ]
        ),
        limits=InquiryLimits(timeout_seconds=0.02),
    )
    assert result["stop_reason"] == "loop_timeout"
    assert result["summary"] is None
    assert result["summary_status"] == "not_available"


async def test_context_over_32k_stops_before_another_model_call(boundary, monkeypatch):
    import importlib.util

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module

    base = module.ToolExecutor

    class LargeObservationExecutor(base):
        async def execute(self, *args):
            value = await super().execute(*args)
            value["reason"] = "x" * 12000
            return value

    class CountingModel(SequenceModel):
        count = 0

        async def next(self, messages, run_id):
            self.count += 1
            return await super().next(messages, run_id)

    model = CountingModel(
        [
            ModelTurn(calls=[call(boundary, f"call_{i}", i) for i in range(3)]),
            ModelTurn(final=FinalAnswer(summary="candidate", evidence_call_ids=[])),
        ]
    )
    monkeypatch.setattr(module, "ToolExecutor", LargeObservationExecutor)
    result = await boundary.run(model)
    assert result["stop_reason"] == "input_too_large"
    assert model.count == result["model_steps"] == 1
    assert len(result["results"]) == 3
    assert result["attempts"] == result["wire_calls"] == 3
    assert result["summary"] is None


async def test_preparation_overrun_cannot_start_model(boundary, monkeypatch):
    import importlib.util
    from time import sleep

    assert importlib.util.find_spec("anlan.workflows.external_inquiry_personnel"), (
        "personnel workflow missing"
    )
    from anlan.workflows import external_inquiry_personnel as module
    from anlan.workflows.external_inquiry_personnel import InquiryLimits

    class NeverCalled(SequenceModel):
        count = 0

        async def next(self, messages, run_id):
            self.count += 1
            return ModelTurn(final=FinalAnswer(summary="candidate", evidence_call_ids=[]))

    async def slow_prepare(*args):
        sleep(0.04)
        return boundary.snapshot

    monkeypatch.setattr(module, "prepare_personnel", slow_prepare)
    model = NeverCalled([])
    result = await boundary.run(model, limits=InquiryLimits(timeout_seconds=0.02))
    assert result["stop_reason"] == "loop_timeout"
    assert model.count == 0
