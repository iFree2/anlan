import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

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


def test_wheel_resources_include_new_sql_and_keep_old_migration_checks(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "package_verifier", "scripts/verify_package_layout.py",
    )
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    root = Path.cwd()
    resources = [*(root / "src/anlan/sql").glob("*.sql"),
                 *(root / "src/anlan/assets").glob("*")]
    wheel = tmp_path / "resources.whl"

    def archive_without(omitted=None, corrupt=None):
        with zipfile.ZipFile(wheel, "w") as archive:
            for resource in resources:
                name = resource.relative_to(root / "src").as_posix()
                if name != omitted:
                    archive.writestr(name, b"wrong contents" if name == corrupt
                                     else resource.read_bytes())

    archive_without()
    with zipfile.ZipFile(wheel) as archive:
        checked = verifier.verify_resources(archive, root)
    assert len(checked) == len(resources)
    names = {item["path"] for item in checked}
    assert "anlan/sql/017_collaboration.sql" in names
    assert "anlan/sql/021_business_queries.sql" in names
    assert {resource.relative_to(root / "src").as_posix()
            for resource in (root / "src/anlan/sql").glob("*.sql")} <= names
    archive_without("anlan/sql/001_registry.sql")
    with zipfile.ZipFile(wheel) as archive, pytest.raises(KeyError):
        verifier.verify_resources(archive, root)
    archive_without(corrupt="anlan/sql/017_collaboration.sql")
    with zipfile.ZipFile(wheel) as archive, pytest.raises(ValueError, match="differs"):
        verifier.verify_resources(archive, root)


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
