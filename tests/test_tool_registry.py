import pytest
from test_tool_executor import ACTOR, REFS, catalog


def test_registry_rejects_duplicate_and_catalog_is_immutable():
    from anlan.tools.registry import ToolRegistry

    task = catalog()
    definition = task.definitions[0]
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([definition, definition])
    assert {s["function"]["name"] for s in task.schemas()} == {d.name for d in task.definitions}
    schema = task.schemas()
    schema.clear()
    assert len(task.schemas()) == 2
    with pytest.raises((AttributeError, TypeError)):
        task.identity = ACTOR
    assert REFS.area_id == "area-001"


def test_model_binding_does_not_mutate_shared_instance():
    from anlan.llm.config import ModelConfig
    from anlan.llm.tool_model import DeepSeekToolModel

    model = DeepSeekToolModel(ModelConfig(api_key="test"), None, None, include_knowledge=True)
    original = model.tool_schemas
    bound = model.bind_catalog(catalog())
    assert bound is not model
    assert len(bound.tool_schemas) == 2 and len(model.tool_schemas) == 3
    assert model.tool_schemas is original


async def test_parallel_bound_model_requests_use_their_own_catalog():
    import asyncio
    import json

    import httpx
    from test_tool_model import FakeLedger, call, envelope

    from anlan.llm.config import ModelConfig
    from anlan.llm.tool_model import DeepSeekToolModel
    from anlan.tools.policy import TaskCatalog

    task = catalog()
    area_only = TaskCatalog(
        task.identity,
        tuple(d for d in task.definitions if d.name == "query_area_status"),
        tuple(g for g in task.grants if g[0] == "query_area_status"),
    )
    seen = {}

    async def handler(request):
        payload = json.loads(request.content)
        seen[payload["messages"][0]["content"]] = {s["function"]["name"] for s in payload["tools"]}
        await asyncio.sleep(0)
        return httpx.Response(200, json=envelope({"content": None, "tool_calls": [call()]}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekToolModel(
            ModelConfig(api_key="test"), client, FakeLedger(), include_knowledge=True
        )
        await asyncio.gather(
            model.bind_catalog(task).next([{"role": "user", "content": "full"}], "full"),
            model.bind_catalog(area_only).next([{"role": "user", "content": "area"}], "area"),
        )
    assert seen == {
        "full": {"query_area_status", "query_worker_qualification"},
        "area": {"query_area_status"},
    }
    assert len(model.tool_schemas) == 3


async def test_bound_gateway_attempts_are_private_and_ledger_shared():
    import asyncio
    import json

    import httpx
    from test_tool_model import FakeLedger, call, envelope

    from anlan.llm.config import ModelConfig
    from anlan.llm.contracts import AnalysisFailure
    from anlan.llm.tool_model import DeepSeekToolModel

    first_reserved = asyncio.Event()
    second_finished = asyncio.Event()

    async def handler(request):
        label = json.loads(request.content)["messages"][0]["content"]
        if label == "A":
            first_reserved.set()
            await second_finished.wait()
            return httpx.Response(429)
        second_finished.set()
        return httpx.Response(200, json=envelope({"content": None, "tool_calls": [call()]}))

    ledger = FakeLedger()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = DeepSeekToolModel(ModelConfig(api_key="test", max_requests=1), client, ledger)
        a, b = model.bind_catalog(catalog()), model.bind_catalog(catalog())
        task = asyncio.create_task(a.next([{"role": "user", "content": "A"}], "A"))
        await first_reserved.wait()
        await b.next([{"role": "user", "content": "B"}], "B")
        with pytest.raises(AnalysisFailure, match="model_rate_limited"):
            await task
        assert a.gateway.last_attempt_id == "1"
        assert b.gateway.last_attempt_id == "2"
        assert a.gateway.ledger is b.gateway.ledger is ledger
        assert a.gateway.requests_used == b.gateway.requests_used == 1
        with pytest.raises(AnalysisFailure, match="budget_exceeded"):
            await b.next([{"role": "user", "content": "B"}], "B")
