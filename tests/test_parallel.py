import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from test_context import SNAPSHOT
from test_tools import NOW, OWNER

from anlan.registry import AccessDenied, InvalidTransition
from anlan.tools.queries import FactTools

REFS = {"worker_id": "worker-001", "qualification_type": "welding", "area_id": "area-001"}


class Service:
    async def get(self, identity, task_id):
        return copy.deepcopy(SNAPSHOT)


class Memory:
    async def list_active(self, identity):
        return []


class Knowledge:
    clock = staticmethod(lambda: NOW)

    async def search(self, identity, parameters):
        return {"outcome": "unknown", "reason": "no_relevant_knowledge",
                "queried_at": NOW.isoformat(), "citations": []}


def tools():
    return FactTools(Path("examples/synthetic/facts-v1"), clock=lambda: NOW)


async def collect(**kwargs):
    from anlan.parallel import collect_parallel
    return await collect_parallel(kwargs.pop("service", Service()), OWNER, SNAPSHOT["task_id"],
        kwargs.pop("references", REFS), "监护要求？", kwargs.pop("tools", tools()),
        kwargs.pop("knowledge_store", Knowledge()), kwargs.pop("memory_store", Memory()), **kwargs)


def test_parallel_module_exists():
    assert importlib.util.find_spec("anlan.parallel") is not None


async def test_parallel_overlap_and_minimum_context():
    entered = asyncio.Event()
    released = asyncio.Event()
    base = tools()

    class Facts:
        clock = staticmethod(base.clock)

        async def query_worker_qualification(self, identity, parameters):
            entered.set()
            await released.wait()
            return await base.query_worker_qualification(identity, parameters)

        query_area_status = base.query_area_status

    class Search(Knowledge):
        async def search(self, identity, parameters):
            await entered.wait()
            released.set()
            return await super().search(identity, parameters)

    bundle = await collect(tools=Facts(), knowledge_store=Search())
    assert [o["outcome"] for o in bundle["observations"]] == ["ok", "ok", "unknown"]
    run = bundle["collection"]
    assert run["tool_calls"] == 3 and len(run["children"]) == 2
    facts, knowledge = run["children"]
    assert facts["input"]["parameters"] == REFS
    assert knowledge["input"]["parameters"] == {"question": "监护要求？"}
    for child in run["children"]:
        assert child["parent_run_id"] == run["run_id"]
        assert child["input"]["revision"] == SNAPSHOT["revision"]
        assert "fields" not in child["input"] and "memories" not in child["input"]


@pytest.mark.parametrize("limit", [0, 1, 2, 3])
async def test_deterministic_parent_budget(limit):
    from anlan.parallel import CollectionLimits
    result = await collect(limits=CollectionLimits(tool_calls=limit))
    assert result["collection"]["tool_calls"] == limit
    assert [o["reason"] for o in result["observations"][limit:]] == [
        "parent_tool_budget_exceeded"] * (3 - limit)


async def test_identity_precedes_all_dependencies():
    from anlan.parallel import collect_parallel

    class Denied:
        async def get(self, *args):
            raise AccessDenied("denied")

    class Never:
        def __getattr__(self, name):
            raise AssertionError("dependency before authorization")

    with pytest.raises(AccessDenied):
        await collect_parallel(Denied(), OWNER, "task", {}, "q", Never(), Never(), Never())


async def test_cross_object_access_denied_without_losing_other_evidence():
    result = await collect(references={**REFS, "worker_id": "other-user-object"})
    assert result["observations"][0]["reason"] == "access_denied"
    assert result["observations"][0]["source"] is None
    assert result["observations"][1]["outcome"] == "ok"


async def test_partial_timeout_retains_finished_worker_and_knowledge():
    from anlan.parallel import CollectionLimits
    base = tools()
    cleaned = asyncio.Event()

    class Slow:
        clock = staticmethod(base.clock)
        query_worker_qualification = base.query_worker_qualification

        async def query_area_status(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                cleaned.set()

    result = await collect(tools=Slow(), limits=CollectionLimits(timeout_seconds=0.15))
    assert cleaned.is_set()
    assert result["observations"][0]["outcome"] == "ok"
    assert result["observations"][1]["reason"] == "parent_deadline_exceeded"
    assert result["observations"][2]["reason"] == "no_relevant_knowledge"


@pytest.mark.parametrize("external", [False, True])
async def test_cancellation_propagates_and_cleans_children(external):
    event, entered, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Slow(Knowledge):
        async def search(self, *args):
            entered.set()
            try:
                await asyncio.sleep(10)
            finally:
                cleaned.set()

    task = asyncio.create_task(collect(knowledge_store=Slow(), cancel_event=event))
    await asyncio.wait_for(entered.wait(), timeout=2)
    if external:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        event.set()
        result = await task
        assert result["collection"]["stop_reason"] == "cancelled"
        assert result["observations"][2]["reason"] == "parent_cancelled"
    assert cleaned.is_set()


async def test_changed_material_rejected():
    class Changed(Service):
        calls = 0

        async def get(self, *args):
            value = await super().get(*args)
            self.calls += 1
            value["revision"] += self.calls - 1
            return value

    with pytest.raises(InvalidTransition):
        await collect(service=Changed())


async def test_late_success_discarded_and_adapter_failure_is_unknown():
    from anlan.parallel import CollectionLimits
    base = tools()

    class Late:
        clock = staticmethod(base.clock)

        async def query_worker_qualification(self, *args):
            value = await base.query_worker_qualification(*args)
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return value

        async def query_area_status(self, *args):
            raise RuntimeError("private-sentinel")

    result = await collect(tools=Late(), limits=CollectionLimits(timeout_seconds=0.1))
    assert result["observations"][0]["reason"] == "parent_deadline_exceeded"
    assert result["observations"][1]["outcome"] != "ok"
    assert "private-sentinel" not in json.dumps(result)
    normal = await collect(tools=Late())
    assert normal["observations"][1]["reason"] == "branch_tool_error"


async def test_result_object_and_time_must_match_host_input():
    base = tools()

    class Wrong:
        clock = staticmethod(base.clock)
        query_area_status = base.query_area_status

        async def query_worker_qualification(self, *args):
            value = await base.query_worker_qualification(*args)
            return value.model_copy(update={"object_id": "forged"})

    result = await collect(tools=Wrong())
    assert result["observations"][0]["reason"] == "branch_contract_conflict"
    assert result["observations"][1]["outcome"] == "ok"


async def test_source_conflict_is_explicit_not_voted():
    base = tools()
    worker = await base.query_worker_qualification(OWNER, {
        "worker_id": "worker-001", "qualification_type": "welding"})

    class Conflicting:
        clock = staticmethod(base.clock)
        query_worker_qualification = base.query_worker_qualification

        async def query_area_status(self, *args):
            value = await base.query_area_status(*args)
            return value.model_copy(update={"source": worker.source.model_copy(
                update={"sha256": "0" * 64})})

    result = await collect(tools=Conflicting())
    assert len(result["collection"]["conflicts"]) == 1
    assert [o["reason"] for o in result["observations"][:2]] == ["source_conflict"] * 2
    assert len(result["collection"]["rejected_observations"]) == 2


async def test_serial_parallel_canonical_equivalence():
    from anlan.parallel import canonical_observations
    serial = await collect(parallel=False)
    parallel = await collect()
    assert canonical_observations(serial["observations"]) == canonical_observations(
        parallel["observations"])


async def test_external_cancel_during_deadline_cleanup_still_propagates():
    from anlan.parallel import CollectionLimits
    cleanup = asyncio.Event()

    class Slow(Knowledge):
        async def search(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                cleanup.set()
                await asyncio.sleep(10)

    task = asyncio.create_task(collect(knowledge_store=Slow(),
        limits=CollectionLimits(timeout_seconds=0.05)))
    await asyncio.wait_for(cleanup.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)


@pytest.mark.parametrize("cancel", [False, True])
async def test_parent_deadline_and_cancellation_cover_memory(cancel):
    from anlan.parallel import CollectionLimits
    entered, event = asyncio.Event(), asyncio.Event()

    class SlowMemory:
        async def list_active(self, *args):
            entered.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(collect(memory_store=SlowMemory(), cancel_event=event,
        limits=CollectionLimits(timeout_seconds=0.15)))
    await asyncio.wait_for(entered.wait(), 2)
    if cancel:
        event.set()
    result = await asyncio.wait_for(task, 2)
    assert result["collection"]["stop_reason"] == ("cancelled" if cancel else "deadline_exceeded")
    assert result["observations"][0]["outcome"] == "ok"
    assert "memory_not_read_after_stop" in result["warnings"]


async def test_memory_uses_same_frozen_as_of_without_mutating_store():
    from datetime import timedelta

    class TimedMemory:
        clock = staticmethod(lambda: NOW + timedelta(seconds=1))

        async def list_active(self, *args):
            return [{"visible": True}] if self.clock() == NOW else []

    memory = TimedMemory()
    result = await collect(memory_store=memory)
    assert result["memories"] == [{"visible": True}]
    assert memory.clock() == NOW + timedelta(seconds=1)


async def test_cancel_during_final_material_check_is_recorded():
    event = asyncio.Event()

    class Finalizing(Service):
        calls = 0

        async def get(self, *args):
            self.calls += 1
            if self.calls == 2:
                event.set()
                await asyncio.sleep(0)
            return await super().get(*args)

    result = await collect(service=Finalizing(), cancel_event=event)
    assert result["collection"]["stop_reason"] == "cancelled"

