"""Scoped official MCP client exposing the same two FactTools methods to the host."""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from anlan.business_bridge import SCHEMAS, failure, validate_url
from anlan.tools.contracts import ToolResult


class RequestTrackingStream:
    """Track wire IDs at the public transport boundary, without SDK private counters."""

    def __init__(self, stream, pending):
        self.stream, self.pending = stream, pending

    async def send(self, message):
        request = message.message.root
        if isinstance(request, types.JSONRPCRequest) and request.method == "tools/call":
            self.pending[asyncio.current_task()] = request.id
        await self.stream.send(message)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)


class McpFactTools:
    def __init__(self, session, identity, now):
        self.session, self.identity, self.now = session, identity.model_copy(deep=True), now
        self.clock = lambda: now
        self.pending = {}

    async def _cancel_remote(self):
        request_id = self.pending.get(asyncio.current_task())
        if request_id is not None:
            try:
                await asyncio.wait_for(self.session.send_notification(types.ClientNotification(
                    types.CancelledNotification(params=types.CancelledNotificationParams(
                        requestId=request_id, reason="host_cancelled_or_timed_out")))), 0.5)
            except Exception:
                pass  # Transport may already be gone; owned stdio context also cleans the process.

    async def query_worker_qualification(self, identity, parameters):
        return await self._call("query_worker_qualification", identity, parameters)

    async def query_area_status(self, identity, parameters):
        return await self._call("query_area_status", identity, parameters)

    async def _call(self, name, identity, parameters):
        if identity != self.identity:
            return failure(name, parameters, self.now, "access_denied")
        try:
            SCHEMAS[name].model_validate(parameters)
        except ValueError:
            return failure(name, parameters, self.now, "invalid_parameters")
        try:
            async with asyncio.timeout(5):
                response = await self.session.call_tool(
                    name, parameters, read_timeout_seconds=timedelta(seconds=4)
                )
            result = ToolResult.model_validate(response.structuredContent)
            if (
                result.tool != name
                or result.object_id != parameters.get("worker_id", parameters.get("area_id"))
                or result.queried_at != self.now
            ):
                raise ValueError("MCP result binding mismatch")
            return result
        except asyncio.CancelledError:
            await self._cancel_remote()
            raise
        except TimeoutError:
            await self._cancel_remote()
            return failure(name, parameters, self.now, "timeout")
        except McpError as exc:
            if exc.error.code == 408:
                await self._cancel_remote()
                return failure(name, parameters, self.now, "timeout")
            return failure(name, parameters, self.now, "data_error")
        except Exception:
            return failure(name, parameters, self.now, "data_error")
        finally:
            self.pending.pop(asyncio.current_task(), None)


@asynccontextmanager
async def mcp_fact_tools(url, token, identity, now):
    validate_url(url)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "anlan.mcp_server"],
        env={
            "ANLAN_JAVA_URL": url,
            "ANLAN_API_TOKEN": token,
            "ANLAN_AS_OF": now.isoformat(),
            "ANLAN_TENANT": identity.tenant_id,
            "ANLAN_USER": identity.user_id,
            "PYTHONIOENCODING": "utf-8",
        },
    )
    async with stdio_client(parameters) as (read, write):
        pending = {}
        async with ClientSession(read, RequestTrackingStream(write, pending),
                                 read_timeout_seconds=timedelta(seconds=8)) as session:
            info = await session.initialize()
            tools = McpFactTools(session, identity, now)
            tools.pending = pending
            yield tools, session, info
