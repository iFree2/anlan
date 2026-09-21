import asyncio
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from test_tools import NOW, OWNER

from anlan.parallel import canonical_observations
from anlan.tools.queries import FactTools


def test_bridge_module_exists():
    assert importlib.util.find_spec("anlan.business_bridge") is not None


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    sys.path.insert(0, str(Path("scripts").resolve()))
    from bridge_support import bridge_stack

    with bridge_stack(
        Path("examples/synthetic/facts-v1"), OWNER, NOW, tmp_path_factory.mktemp("java")
    ) as stack:
        yield stack


def test_java_http_returns_existing_python_facts(bridge):
    with httpx.Client(trust_env=False) as client:
        response = client.post(
            bridge.url + "/api/area-status", json={"area_id": "area-001"}, headers=bridge.headers
        )
    assert response.status_code == 200
    direct = asyncio.run(
        FactTools(Path("examples/synthetic/facts-v1"), clock=lambda: NOW).query_area_status(
            OWNER, {"area_id": "area-001"}
        )
    )
    assert canonical_observations([response.json()]) == canonical_observations(
        [direct.model_dump(mode="json")]
    )


@pytest.mark.parametrize(
    "path,token,parameters,status,reason",
    [
        ("/api/area-status", False, {"area_id": "area-001"}, 401, None),
        ("/api/approve", True, {}, 404, None),
        (
            "/api/area-status",
            True,
            {"area_id": "area-001", "tenant_id": "forged"},
            200,
            "invalid_parameters",
        ),
        ("/api/area-status", True, {"area_id": "other-private-area"}, 200, "access_denied"),
    ],
)
def test_java_permissions_and_allowlist(bridge, path, token, parameters, status, reason):
    with httpx.Client(trust_env=False) as client:
        result = client.post(
            bridge.url + path,
            json=parameters,
            headers={
                **bridge.headers,
                "Authorization": "Bearer " + (bridge.token if token else "wrong"),
            },
        )
    assert result.status_code == status
    if reason:
        assert result.json()["reason"] == reason and result.json()["source"] is None


def test_java_oversize_and_wrong_method(bridge):
    with httpx.Client(trust_env=False) as client:
        headers = bridge.headers
        assert (
            client.post(
                bridge.url + "/api/area-status", content=b"x" * 4097, headers=headers
            ).status_code
            == 413
        )
        assert client.get(bridge.url + "/api/area-status", headers=headers).status_code == 405


async def test_actual_mcp_handshake_tools_call_and_scope(bridge):
    from anlan.mcp_tools import mcp_fact_tools

    async with mcp_fact_tools(bridge.url, bridge.token, OWNER, NOW) as (tools, session, info):
        assert info.serverInfo.name == "anlan-read-only-facts"
        listing = await session.list_tools()
        assert {t.name for t in listing.tools} == {
            "query_worker_qualification",
            "query_area_status",
        }
        assert all(t.annotations.readOnlyHint for t in listing.tools)
        result = await tools.query_area_status(OWNER, {"area_id": "area-001"})
        assert result.outcome == "ok" and result.facts["status"] == "restricted"
        denied = await tools.query_area_status(
            OWNER.model_copy(update={"user_id": "outsider"}), {"area_id": "area-001"}
        )
        assert denied.reason == "access_denied"
        forged = await session.call_tool(
            "query_area_status", {"area_id": "area-001", "tenant_id": "other"}
        )
        assert forged.isError
        unknown = await session.call_tool("approve", {})
        assert unknown.isError


async def test_mcp_wrong_token_and_as_of_are_explicit_errors(bridge):
    from anlan.mcp_tools import mcp_fact_tools

    for token, now in [("wrong", NOW), (bridge.token, NOW + timedelta(seconds=1))]:
        async with mcp_fact_tools(bridge.url, token, OWNER, now) as (tools, _, _):
            result = await tools.query_area_status(OWNER, {"area_id": "area-001"})
            assert result.outcome == "error" and result.facts is None


def test_loopback_config_does_not_allow_credential_forwarding():
    from anlan.business_bridge import validate_url

    for url in [
        "https://example.com",
        "http://localhost.evil/",
        "http://user@127.0.0.1:9",
        "http://127.0.0.1:9/path",
        "http://127.0.0.1:9?url=evil",
    ]:
        with pytest.raises(ValueError):
            validate_url(url)


async def test_http_bridge_network_and_contract_failures_are_bounded():
    from anlan.business_bridge import HttpFactClient

    for response in [
        httpx.Response(503),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, json={"approved": True}),
    ]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as c:
            result = await HttpFactClient(
                "http://127.0.0.1:9", "test", NOW, identity=OWNER, client=c
            ).call("query_area_status", {"area_id": "area-001"})
        assert result.outcome == "error" and result.facts is None
        assert "test" not in json.dumps(result.model_dump(mode="json"))


async def test_host_identity_must_match_token_bound_backend_scope(bridge):
    from anlan.mcp_tools import mcp_fact_tools

    wrong = OWNER.model_copy(update={"tenant_id": "other-tenant"})
    async with mcp_fact_tools(bridge.url, bridge.token, wrong, NOW) as (tools, _, _):
        value = await tools.query_area_status(wrong, {"area_id": "area-001"})
    assert value.reason == "access_denied" and value.source is None


@pytest.mark.parametrize("cancel", [True, False])
async def test_actual_sdk_cancel_and_timeout_notify_remote_handler(cancel):
    import anyio
    from mcp import ClientSession
    from mcp.server.lowlevel import Server
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp.types import Tool

    from anlan import mcp_tools

    entered, cleaned = asyncio.Event(), asyncio.Event()
    server = Server("test-slow-server")

    @server.list_tools()
    async def listing():
        return [Tool(name="query_area_status", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call(name, arguments):
        entered.set()
        try:
            await asyncio.sleep(10)
            return []
        finally:
            cleaned.set()

    async with create_client_server_memory_streams() as (client, backend):
        pending = {}
        writer = getattr(mcp_tools, "RequestTrackingStream", lambda stream, _: stream)(
            client[1], pending)
        async with anyio.create_task_group() as group:
            group.start_soon(server.run, *backend, server.create_initialization_options())
            async with ClientSession(client[0], writer) as session:
                await session.initialize()
                tools = mcp_tools.McpFactTools(session, OWNER, NOW)
                tools.pending = pending
                task = asyncio.create_task(tools.query_area_status(OWNER, {"area_id": "area-001"}))
                await asyncio.wait_for(entered.wait(), 2)
                if cancel:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    result = await task
                    assert result.reason == "timeout"
                await asyncio.wait_for(cleaned.wait(), 0.5)
                assert not pending
            group.cancel_scope.cancel()


@pytest.mark.parametrize("fault,status", [
    ("unavailable", 502), ("timeout", 504), ("oversize", 502)])
def test_java_real_backend_failures(tmp_path, fault, status):
    import time

    from bridge_support import bridge_stack

    with bridge_stack(Path("examples/synthetic/facts-v1"), OWNER, NOW, tmp_path) as stack:
        if fault == "unavailable":
            stack.server.shutdown()
            stack.server.server_close()
        else:
            original = stack.server.RequestHandlerClass.do_POST

            def injected(handler):
                if fault == "timeout":
                    time.sleep(2.5)
                    original(handler)
                else:
                    handler.reply(200, {"oversize": "x" * 65537})

            stack.server.RequestHandlerClass.do_POST = injected
        with httpx.Client(trust_env=False, timeout=4) as client:
            result = client.post(stack.url + "/api/area-status", json={"area_id": "area-001"},
                                 headers=stack.headers)
        assert result.status_code == status
