import pytest

from anlan.common.errors import InvalidTransition
from anlan.common.models import Identity
from anlan.interfaces.cli import DEMO_FIELDS, DEMO_PATCHES
from anlan.workflows.material_analysis import Analysis, OfflineAnalyzer
from anlan.workflows.service import WorkflowService

OWNER = Identity(tenant_id="synthetic-recovery", user_id="learner")


async def test_same_request_returns_original_result_without_reanalysis():
    class Counter:
        calls = 0

        async def analyze(self, application):
            self.calls += 1
            return Analysis(semantic_status="checked")

    analyzer = Counter()
    service = WorkflowService(analyzer)
    first = await service.start(OWNER, DEMO_FIELDS)
    second = await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="r1")
    duplicate = await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="r1")
    assert duplicate == second
    assert analyzer.calls == 2
    with pytest.raises(InvalidTransition, match="request_id"):
        await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[1], request_id="r1")
    with pytest.raises(InvalidTransition):
        await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[1], request_id="r2")
    assert await service.get(OWNER, first["task_id"]) == second


async def test_recovery_after_patch_checkpoint_keeps_run_and_revision():
    class FailOnce:
        calls = 0

        async def analyze(self, application):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated process failure during analyze")
            return Analysis(semantic_status="checked")

    analyzer = FailOnce()
    service = WorkflowService(analyzer)
    first = await service.start(OWNER, DEMO_FIELDS)
    with pytest.raises(RuntimeError):
        await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="crash")
    interrupted = await service.get(OWNER, first["task_id"])
    assert interrupted["revision"] == 2
    assert interrupted["status"] == "analyzing"
    with pytest.raises(InvalidTransition, match="recover"):
        await service.resume(OWNER, first["task_id"], 2, DEMO_PATCHES[1], request_id="new")
    recovered = await service.recover(OWNER, first["task_id"])
    assert recovered["revision"] == 2
    assert recovered["run_id"] == interrupted["run_id"]
    assert recovered["status"] == "waiting_input"
    assert recovered["fields"]["work_location_description"] == DEMO_PATCHES[0][
        "work_location_description"]
    assert await service.resume(
        OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="crash"
    ) == recovered
    history = await service.history(OWNER, first["task_id"])
    assert [row["status"] for row in history] == ["completed", "completed"]


async def test_recover_at_interrupt_is_read_only():
    service = WorkflowService(OfflineAnalyzer())
    first = await service.start(OWNER, DEMO_FIELDS)
    assert await service.recover(OWNER, first["task_id"]) == first


async def test_crash_between_analysis_and_interrupt_still_allows_next_supplement(monkeypatch):
    service = WorkflowService(OfflineAnalyzer())
    first = await service.start(OWNER, DEMO_FIELDS)
    invoke = service._graph.ainvoke

    async def crash_after_analysis(graph_input, config, **kwargs):
        await invoke(graph_input, config, interrupt_after=["analyze"], **kwargs)
        raise RuntimeError("crash before ask entered")

    with monkeypatch.context() as context:
        context.setattr(service._graph, "ainvoke", crash_after_analysis)
        with pytest.raises(RuntimeError):
            await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="edge")
    recovered = await service.recover(OWNER, first["task_id"])
    assert recovered["revision"] == 2
    final = await service.resume(OWNER, first["task_id"], 2, DEMO_PATCHES[1], request_id="after")
    assert final["status"] == "awaiting_review"


async def test_cached_result_does_not_bypass_contract_version_check():
    service = WorkflowService(OfflineAnalyzer())
    first = await service.start(OWNER, DEMO_FIELDS)
    await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="cached")
    service._registry.records[first["task_id"]].contract_version = "incompatible-v99"
    with pytest.raises(InvalidTransition, match="版本"):
        await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="cached")
