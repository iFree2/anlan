"""Executor JSON normalization for timed dynamic business parameters."""

import json
from datetime import UTC, datetime

from pydantic import AwareDatetime

from anlan.common.models import Identity, StrictModel
from anlan.tools.executor import ToolExecutor
from anlan.tools.policy import TaskCatalog
from anlan.tools.registry import ToolDefinition


async def test_timed_parameters_match_same_canonical_json_task_grant():
    class Request(StrictModel):
        queried_at: AwareDatetime

    class Observation(StrictModel):
        tool: str
        object_id: None = None
        queried_at: AwareDatetime
        outcome: str = "ok"

    when = datetime(2026, 1, 1, tzinfo=UTC)
    actor = Identity(tenant_id="tenant", user_id="reader")
    calls = []

    async def handler(identity, parameters):
        calls.append(parameters)
        return Observation(tool="dynamic_alias", queried_at=when)

    definition = ToolDefinition(
        "dynamic_alias", "synthetic", Request, Observation, handler, lambda: when
    )
    raw = Request(queried_at=when).model_dump_json()
    catalog = TaskCatalog(actor, (definition,), (("dynamic_alias", raw),))
    result = await ToolExecutor(catalog).execute("dynamic_alias", raw)
    assert result["outcome"] == "ok" and result["evidence_valid"]
    assert calls == [json.loads(raw)]


async def test_fixed_host_failure_code_survives_executor_without_valid_evidence():
    from anlan.tools.dynamic_mcp.runtime import RuntimeFailure

    class Request(StrictModel):
        pass

    async def disconnected(identity, parameters):
        raise RuntimeFailure("disconnected")

    definition = ToolDefinition(
        "dynamic_alias", "synthetic", Request, Request, disconnected, lambda: datetime.now(UTC)
    )
    catalog = TaskCatalog(
        Identity(tenant_id="t", user_id="u"), (definition,), (("dynamic_alias", "{}"),)
    )
    result = await ToolExecutor(catalog).execute("dynamic_alias", "{}")
    assert result["reason"] == "disconnected"
    assert result["executed"] and not result["evidence_valid"]
