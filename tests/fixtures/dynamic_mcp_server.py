"""Fixed synthetic MCP server; event log contains wire metadata only."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
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


@server.list_tools()
async def tools(request: types.ListToolsRequest):
    mode = sys.argv[1]
    if mode == "business":
        from anlan.tools.dynamic_mcp.catalog import expected_schemas

        input_schema, output_schema = expected_schemas("equipment.asset.query")
        return types.ListToolsResult(
            tools=[types.Tool(name="assets", inputSchema=input_schema, outputSchema=output_schema)]
        )
    if mode == "slow":
        await asyncio.sleep(60)
    if mode == "disconnect":
        os._exit(0)
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    if mode == "bad_ref":
        schema["$ref"] = "https://untrusted.invalid/schema"
    if mode == "oversize":
        schema["description"] = "x" * (70 * 1024)
    tool = types.Tool(
        name="synthetic_two" if request.params and mode != "duplicate" else "synthetic_one",
        description="REMOTE_SECRET_DO_NOT_RETAIN",
        inputSchema=schema,
        outputSchema=None
        if mode == "missing_output"
        else {
            "type": "object",
            "properties": {"synthetic": {"type": "boolean"}},
            "required": ["synthetic"],
            "additionalProperties": False,
        },
    )
    return types.ListToolsResult(tools=[tool], nextCursor=None if request.params else "second")


@server.call_tool()
async def call(name, arguments):
    if arguments.get("slow"):
        await asyncio.sleep(60)
    return types.CallToolResult(content=[], structuredContent={"synthetic": True})


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
