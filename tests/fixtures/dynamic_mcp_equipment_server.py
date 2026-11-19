"""M3 three-capability synthetic MCP server; event log contains wire metadata only."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


def event(**values):
    with Path(sys.argv[2]).open("a", encoding="utf-8") as output:
        output.write(json.dumps({"pid": os.getpid(), **values}) + "\n")


class TrackedReader:
    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __aiter__(self):
        return self

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    async def __anext__(self):
        message = await self.stream.__anext__()
        root = message.message.root
        params = getattr(root, "params", {}) or {}
        event(
            method=getattr(root, "method", "response"),
            request_id=getattr(root, "id", None),
            cancelled_id=params.get("requestId"),
        )
        return message


server = Server("synthetic-fixture", version="1")


CAPABILITIES = ("equipment.asset.query", "equipment.inspection.query", "equipment.fault.query")


@server.list_tools()
async def tools(request: types.ListToolsRequest):
    from anlan.tools.dynamic_mcp.catalog import expected_schemas

    result = types.ListToolsResult(
        tools=[
            types.Tool(
                name=cap,
                inputSchema=expected_schemas(cap)[0],
                outputSchema=expected_schemas(cap)[1],
            )
            for cap in CAPABILITIES
        ]
    )
    if sys.argv[1] == "stale_schema":
        result.tools[0].inputSchema["properties"]["untrusted_extra"] = {"type": "string"}
    return result


@server.call_tool()
async def call(name, arguments):
    if sys.argv[1] == "disconnect":
        os._exit(0)
    if sys.argv[1] == "slow":
        await asyncio.sleep(60)
    query_at = datetime.fromisoformat(arguments["queried_at"].replace("Z", "+00:00"))
    start, end = query_at - timedelta(days=365), query_at + timedelta(days=365)
    obj, factory = arguments["objects"][0], arguments["factory_id"]
    base = dict(object_id=obj, record_id="synthetic-record", original_status="synthetic")
    if name == "equipment.asset.query":
        data = dict(
            base,
            name="synthetic-crane",
            equipment_type="crane",
            factory_id=factory,
            status="in_use",
        )
    elif name == "equipment.inspection.query":
        data = dict(
            base,
            category="annual",
            valid_from=start.isoformat(),
            valid_until=end.isoformat(),
            inspection_at=start.isoformat(),
            status="valid",
        )
    else:
        data = dict(base, status="open", observed_at=(query_at - timedelta(days=1)).isoformat())
    value = dict(
        schema_version="dynamic-evidence-v1",
        capability=arguments["capability"],
        contract_version="1",
        data_origin="SYNTHETIC",
        factory_id=factory,
        objects=[obj],
        queried_at=(query_at + timedelta(days=1)).isoformat()
        if sys.argv[1] == "wrong_time"
        else query_at.isoformat(),
        outcome="ok",
        reason=None,
        data=[data],
        sources=[
            dict(
                system_id="synthetic-eam",
                record_id="synthetic-record",
                version="v1",
                updated_at=start.isoformat(),
                valid_from=start.isoformat(),
                valid_until=end.isoformat(),
            )
        ],
        complete=sys.argv[1] != "partial",
        next_cursor="next-page" if sys.argv[1] == "partial" else None,
        coverage=arguments.get("coverage") or dict(object_ids=[obj], start=None, end=None),
    )
    mode = sys.argv[1]
    if mode == "wrong_object":
        value["objects"] = ["E999"]
        value["coverage"]["object_ids"] = ["E999"]
        value["data"][0]["object_id"] = "E999"
    elif mode == "wrong_capability":
        value["capability"] = "equipment.fault.query"
        value["data"] = []
    elif mode == "missing_source":
        value["sources"] = []
    elif mode == "oversized":
        value["sources"] = [dict(value["sources"][0], version="a" * 300)] * 100
        value["data"] = [dict(data, original_status="b" * 300)] * 100
    elif mode == "partial_empty":
        value.update(data=[], complete=False, next_cursor="next-page")
    elif mode == "is_error":
        return types.CallToolResult(content=[], structuredContent=value, isError=True)
    return types.CallToolResult(content=[], structuredContent=value)


async def main():
    event(event="started")
    if sys.argv[1] == "http":
        import uvicorn
        from mcp.server.transport_security import TransportSecuritySettings
        from starlette.applications import Starlette
        from starlette.routing import Route

        manager = StreamableHTTPSessionManager(
            server,
            json_response=True,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

        async def endpoint(scope, receive, send):
            event(method=scope["method"], path=scope["path"])

            async def tracked_receive():
                message = await receive()
                if message.get("body"):
                    try:
                        body = json.loads(message["body"])
                        event(
                            method=body.get("method"),
                            request_id=body.get("id"),
                            cancelled_id=body.get("params", {}).get("requestId"),
                        )
                    except ValueError:
                        pass
                return message

            await manager.handle_request(scope, tracked_receive, send)

        @asynccontextmanager
        async def lifespan(app):
            async with manager.run():
                yield

        class Endpoint:
            async def __call__(self, scope, receive, send):
                await endpoint(scope, receive, send)

        app = Starlette(
            routes=[Route("/mcp", Endpoint(), methods=["GET", "POST", "DELETE"])], lifespan=lifespan
        )
        await uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=int(sys.argv[3]), log_level="critical")
        ).serve()
    else:
        async with stdio_server() as (read, write):
            await server.run(TrackedReader(read), write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
