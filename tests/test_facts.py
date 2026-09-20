import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from anlan.analysis import OfflineAnalyzer
from anlan.cli import DEMO_FIELDS
from anlan.contracts import Identity
from anlan.service import AccessDenied, WorkflowService
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace

OWNER = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
REFS = {"worker_id": "worker-001", "qualification_type": "welding", "area_id": "area-001"}
NOW = datetime.fromisoformat("2026-09-20T12:00:00+00:00")


def tools(**kwargs):
    return FactTools(Path("examples/synthetic/facts-v1"), clock=lambda: NOW, **kwargs)


async def test_evidence_and_trace_link_to_snapshot_without_mutating_task(tmp_path):
    from anlan.facts import check_facts
    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)
    history = await service.history(OWNER, state["task_id"])
    trace = JsonlTrace(tmp_path / "trace.jsonl")
    report = await check_facts(service, OWNER, state["task_id"], REFS, tools(), trace)
    assert report["task_id"] == state["task_id"]
    assert report["correlation_id"] == state["correlation_id"]
    assert report["revision"] == state["revision"]
    assert report["source_run_id"] == state["run_id"]
    assert report["run_id"] != state["run_id"]
    assert report["status"] == "awaiting_review"
    assert [r["outcome"] for r in report["results"]] == ["ok", "ok"]
    assert await service.get(OWNER, state["task_id"]) == state
    assert await service.history(OWNER, state["task_id"]) == history
    events = [json.loads(line) for line in trace.path.read_text(encoding="utf-8").splitlines()]
    tool_events = [e for e in events if e["event"] == "tool_finished"]
    assert [e["tool"] for e in tool_events] == ["query_worker_qualification", "query_area_status"]
    assert events[-1]["event"] == "facts_finished"
    assert events[-1]["elapsed_ms"] >= 0
    assert all(e["run_id"] == report["run_id"] and "facts" not in e for e in events)
    assert events[0]["source"]["sha256"] == report["results"][0]["source"]["sha256"]


async def test_unauthorized_task_never_reaches_tools():
    from anlan.facts import check_facts
    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)

    async def must_not_read(path):
        pytest.fail("unauthorized task reached a tool")

    with pytest.raises(AccessDenied):
        await check_facts(service, Identity(tenant_id="other", user_id=OWNER.user_id),
                          state["task_id"], REFS, tools(reader=must_not_read), JsonlTrace())
    assert await service.get(OWNER, state["task_id"]) == state


async def test_reference_identity_injection_is_rejected():
    from anlan.facts import check_facts
    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)
    with pytest.raises(ValidationError):
        await check_facts(service, OWNER, state["task_id"], {**REFS, "tenant_id": "other"},
                          tools(), JsonlTrace())
    assert await service.get(OWNER, state["task_id"]) == state


async def test_partial_timeout_keeps_area_fact_and_trace_failure_is_visible(tmp_path):
    from anlan.facts import check_facts

    async def slow_worker(path):
        if path.name == "qualifications.json":
            await asyncio.sleep(10)
        return path.read_bytes()

    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)
    report = await check_facts(service, OWNER, state["task_id"], REFS,
                               tools(reader=slow_worker, timeout_seconds=0.05),
                               JsonlTrace(tmp_path))
    assert [r["reason"] for r in report["results"]] == ["timeout", None]
    assert report["trace_warning"] == "trace_write_failed"
    assert await service.get(OWNER, state["task_id"]) == state


async def test_cli_fact_path_never_initializes_model(monkeypatch, tmp_path, capsys):
    from anlan import cli
    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)

    def forbidden():
        pytest.fail("fact CLI attempted to load model configuration")

    @asynccontextmanager
    async def fake_pg(*args, **kwargs):
        yield service

    monkeypatch.setattr(cli.ModelConfig, "from_env", forbidden)
    monkeypatch.setattr(cli, "postgres_service", fake_pg)
    monkeypatch.setattr(cli, "database_url", lambda: "unused-test-dsn")
    await cli.run(SimpleNamespace(
        command="check-facts", tenant=OWNER.tenant_id, user=OWNER.user_id,
        mode="deepseek", storage="postgres", task=state["task_id"],
        refs_file=Path("examples/synthetic/fact-refs.json"),
        facts_dir=Path("examples/synthetic/facts-v1"), as_of=NOW.isoformat(),
        trace=tmp_path / "trace.jsonl"))
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "fixed_read_only_tools"
    assert report["clock_mode"] == "simulated"
    assert report["requests_this_run"] == 0
    assert [r["outcome"] for r in report["results"]] == ["ok", "ok"]


async def test_cli_budget_snapshot_failure_does_not_swallow_finished_evidence(
        monkeypatch, tmp_path, capsys):
    from anlan import cli
    from anlan.budget import BudgetUnavailable
    from anlan.tool_model import ScriptedToolModel

    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)

    @asynccontextmanager
    async def fake_pg(*args, **kwargs):
        yield service

    class Ledger:
        async def snapshot(self):
            raise BudgetUnavailable("safe failure")

    async def fake_ledger():
        return Ledger()

    monkeypatch.setattr(cli, "postgres_service", fake_pg)
    monkeypatch.setattr(cli, "database_url", lambda: "unused")
    monkeypatch.setattr(cli, "production_ledger", fake_ledger)
    monkeypatch.setattr(cli.ModelConfig, "from_env", lambda: None)
    monkeypatch.setattr(cli, "DeepSeekToolModel", lambda *args, **kwargs: ScriptedToolModel())
    await cli.run(SimpleNamespace(
        command="check-facts-agent", tenant=OWNER.tenant_id, user=OWNER.user_id,
        mode="deepseek", storage="postgres", task=state["task_id"],
        refs_file=Path("examples/synthetic/fact-refs.json"),
        facts_dir=Path("examples/synthetic/facts-v1"), as_of=NOW.isoformat(),
        trace=tmp_path / "trace.jsonl"))
    report = json.loads(capsys.readouterr().out)
    assert report["stop_reason"] == "completed"
    assert report["budget_warning"] == "snapshot_unavailable"
    assert [r["outcome"] for r in report["results"]] == ["ok", "ok"]


async def test_cli_embedding_initialization_failure_still_returns_fact_evidence(
        monkeypatch, tmp_path, capsys):
    from anlan import cli
    service = WorkflowService(OfflineAnalyzer())
    state = await service.start(OWNER, DEMO_FIELDS)

    @asynccontextmanager
    async def fake_pg(*args, **kwargs):
        yield service

    async def unavailable():
        raise ValueError("cache-invalid-sentinel")

    monkeypatch.setattr(cli, "postgres_service", fake_pg)
    monkeypatch.setattr(cli, "database_url", lambda: "unused")
    monkeypatch.setattr(cli.LocalEmbeddings, "create", unavailable)
    await cli.run(SimpleNamespace(
        command="check-facts-agent", tenant=OWNER.tenant_id, user=OWNER.user_id,
        mode="offline", storage="postgres", task=state["task_id"],
        refs_file=Path("examples/synthetic/fact-refs.json"),
        facts_dir=Path("examples/synthetic/facts-v1"), as_of=NOW.isoformat(),
        knowledge_question="监护要求？", trace=tmp_path / "trace.jsonl"))
    output = capsys.readouterr().out
    report = json.loads(output)
    assert [r["outcome"] for r in report["results"]] == ["ok", "ok", "error"]
    assert report["results"][-1]["reason"] == "knowledge_unavailable"
    assert "cache-invalid-sentinel" not in output
