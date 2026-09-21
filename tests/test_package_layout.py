import json
import subprocess
import sys

import pytest
from test_business_bridge import bridge  # noqa: F401 -- shared real Java fixture


@pytest.mark.parametrize("module,forbidden", [
    ("anlan.infrastructure.db", ["anlan.workflows.service", "langgraph"]),
    ("anlan.context.assembly", ["psycopg", "anlan.memory.store"]),
    ("anlan.memory.contracts", ["psycopg", "langgraph"]),
    ("anlan.knowledge.contracts", ["psycopg", "anlan.llm.tool_model"]),
])
def test_lightweight_contract_and_connection_imports(module, forbidden):
    script = (
        f"import importlib,sys,json; importlib.import_module({module!r}); "
        "print(json.dumps(sorted(sys.modules)))"
    )
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout)
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in loaded for prefix in forbidden)


def test_common_exception_identity_and_model_contracts():
    import anlan.knowledge.store as store
    import anlan.memory.store as memory
    from anlan.common.errors import AccessDenied
    from anlan.llm.contracts import AnalysisFailure
    from anlan.llm.gateway import AnalysisFailure as GatewayFailure
    from anlan.workflows import service

    assert store.AccessDenied is memory.AccessDenied is service.AccessDenied is AccessDenied
    assert GatewayFailure is AnalysisFailure


async def test_legacy_mcp_module_keeps_real_stdio_contract(bridge):  # noqa: F811 -- pytest fixture
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(command=sys.executable, args=["-m", "anlan.mcp_server"],
        env={"ANLAN_JAVA_URL": bridge.url, "ANLAN_API_TOKEN": bridge.token,
             "ANLAN_TENANT": bridge.identity.tenant_id, "ANLAN_USER": bridge.identity.user_id,
             "ANLAN_AS_OF": bridge.now.isoformat(), "PYTHONIOENCODING": "utf-8"})
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            assert info.serverInfo.name == "anlan-read-only-facts"
            result = await session.call_tool("query_area_status", {"area_id": "area-001"})
            assert not result.isError
            assert result.structuredContent["facts"]["status"] == "restricted"
