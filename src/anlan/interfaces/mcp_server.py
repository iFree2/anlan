"""MCP stdio facade to two Java APIs; configuration never comes from tool arguments."""

import asyncio
import json
import os
from datetime import datetime

import httpx
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from anlan.common.models import Identity
from anlan.tools.contracts import ToolResult
from anlan.tools.http_client import SCHEMAS, HttpFactClient


async def run():
    server = Server("anlan-read-only-facts")
    async with httpx.AsyncClient(trust_env=False) as client:
        bridge = HttpFactClient(
            os.environ["ANLAN_JAVA_URL"],
            os.environ["ANLAN_API_TOKEN"],
            datetime.fromisoformat(os.environ["ANLAN_AS_OF"]),
            client=client,
            identity=Identity(
                tenant_id=os.environ["ANLAN_TENANT"], user_id=os.environ["ANLAN_USER"]
            ),
        )

        @server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name=name,
                    description="SYNTHETIC只读事实；不是作业批准。",
                    inputSchema=schema.model_json_schema(),
                    outputSchema=ToolResult.model_json_schema(),
                    annotations=ToolAnnotations(
                        readOnlyHint=True,
                        destructiveHint=False,
                        idempotentHint=True,
                        openWorldHint=False,
                    ),
                )
                for name, schema in SCHEMAS.items()
            ]

        @server.call_tool()
        async def call_tool(name, arguments):
            result = await bridge.call(name, arguments)
            data = result.model_dump(mode="json")
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
                structuredContent=data,
                isError=result.outcome == "error",
            )

        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
