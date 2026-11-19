"""Short-lived, discovery-only official SDK sessions for host-approved targets.

The SDK stdio reader has no pre-parse line limit. Only trusted executables may
be profiled; the post-parse schema limits are not a subprocess memory sandbox.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import SecretStr

from anlan.tools.executor import ToolExecutionFailure

_OWNED_LOG = ContextVar("dynamic_mcp_owned_log", default=False)


class _RedactSdkLog(logging.Filter):
    def filter(self, record):
        if _OWNED_LOG.get():
            record.msg, record.args, record.exc_info, record.exc_text = (
                "dynamic_mcp_transport_event",
                (),
                None,
                None,
            )
        return True


_LOG_FILTER = _RedactSdkLog()


@dataclass(frozen=True)
class ExecutableProfile:
    tenant_id: str
    executable_ref: str
    executable: str
    argv: tuple[str, ...]
    cwd: str
    credential_env: str | None = None
    env: tuple[tuple[str, str], ...] = ()
    profile_version: str = "1"


@dataclass(frozen=True)
class HttpProfile:
    tenant_id: str
    target_ref: str
    url: str
    synthetic_loopback_http: bool = False
    profile_version: str = "1"


@dataclass(frozen=True)
class TrustedTargets:
    policy_version: str
    executable_profiles: tuple[ExecutableProfile, ...] = ()
    http_profiles: tuple[HttpProfile, ...] = ()


class CredentialResolver(Protocol):
    async def resolve(self, tenant_id: str, credential_ref: str) -> tuple[SecretStr, str]: ...


class EnvironmentCredentials:
    """Host-only mapping of (tenant, ref) to (environment name, generation)."""

    def __init__(self, bindings):
        self._bindings = dict(bindings)

    async def resolve(self, tenant_id, credential_ref):
        try:
            name, generation = self._bindings[(tenant_id, credential_ref)]
            value = os.environ[name]
            if not value or "\n" in value or "\r" in value:
                raise ValueError
            return SecretStr(value), str(generation)
        except (KeyError, ValueError):
            raise RuntimeFailure("credential_unavailable") from None


@dataclass(frozen=True)
class CleanupReceipt:
    status: str = "closed"


class RuntimeFailure(ToolExecutionFailure):
    def __init__(self, code, cleanup_status="closed"):
        self.cleanup_status = cleanup_status
        super().__init__(code)


class _ExactTargetTransport(httpx.AsyncBaseTransport):
    """Check every actual request before credentials can leave this process."""

    def __init__(self, url):
        self._url = httpx.URL(url)
        self._transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
        self.failure = None

    async def handle_async_request(self, request):
        if request.url != self._url:
            self.failure = "target_not_allowed"
            raise RuntimeFailure("target_not_allowed")
        response = await self._transport.handle_async_request(request)
        if 300 <= response.status_code < 400:
            self.failure = "target_not_allowed"
            await response.aclose()
            raise RuntimeFailure("target_not_allowed")
        # Refuse compression before httpx can inflate an unbounded decoded body.
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            self.failure = "oversized_result"
            await response.aclose()
            raise RuntimeFailure("oversized_result")
        response.stream = _BoundedStream(response.stream, self)
        return response

    async def aclose(self):
        await self._transport.aclose()


class _BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream, transport):
        self._stream, self._transport = stream, transport

    async def __aiter__(self):
        size = 0
        async for chunk in self._stream:
            size += len(chunk)
            if size > 512 * 1024:
                self._transport.failure = "oversized_result"
                await self._stream.aclose()
                raise RuntimeFailure("oversized_result")
            yield chunk

    async def aclose(self):
        await self._stream.aclose()


class _TrackingStream:
    def __init__(self, stream, pending):
        self._stream, self._pending = stream, pending

    async def send(self, message):
        request = message.message.root
        if isinstance(request, types.JSONRPCRequest):
            if request.method not in {"initialize", "tools/list"}:
                raise RuntimeFailure("access_denied")
            self._pending.add(request.id)
        await self._stream.send(message)

    def __getattr__(self, name):
        return getattr(self._stream, name)

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._stream.__aexit__(*args)


async def _reject(*args, **kwargs):
    return types.ErrorData(code=types.INVALID_REQUEST, message="Host capability unavailable")


async def _discard_log(*args, **kwargs):
    return None


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


def _exception_code(exc, fallback):
    if isinstance(exc, RuntimeFailure):
        return exc.code
    if isinstance(exc, (anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError)):
        return "disconnected"
    if isinstance(exc, McpError) and exc.error.code == types.CONNECTION_CLOSED:
        return "disconnected"
    from anlan.tools.dynamic_mcp.registry import RegistryError

    if isinstance(exc, RegistryError) and exc.code in {
        "stale_generation",
        "storage_unavailable",
        "access_denied",
    }:
        return exc.code
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            code = _exception_code(child, None)
            if code:
                return code
    # Only these local errors carry a safe, fixed code. Never relay remote text.
    if isinstance(exc, ValueError) and str(exc) in {
        "access_denied",
        "stale_generation",
        "storage_unavailable",
        "schema_unsupported",
        "oversized_result",
        "discovery_incomplete",
    }:
        return str(exc)
    return fallback


class RuntimeManager:
    def __init__(self, targets, credentials, registry_guard, clock=None):
        self._targets, self._credentials, self._guard = targets, credentials, registry_guard
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._active = set()
        self._closed = False
        self._cleanup_failed = False
        self._cancelled_owners = set()
        self._cleaning = set()
        for name in tuple(logging.Logger.manager.loggerDict):
            if name == "client" or name.startswith(("mcp.", "httpcore.", "httpx")):
                logging.getLogger(name).addFilter(_LOG_FILTER)

    def _profile(self, registration):
        connection = registration.connection
        if connection.transport == "stdio":
            profiles = [
                p
                for p in self._targets.executable_profiles
                if p.tenant_id == registration.tenant_id
                and p.executable_ref == connection.executable_ref
            ]
            if len(profiles) != 1 or tuple(connection.argv) != profiles[0].argv:
                raise RuntimeFailure("target_not_allowed")
            profile = profiles[0]
            if (
                not Path(profile.executable).is_absolute()
                or not Path(profile.cwd).is_absolute()
                or Path(profile.executable).stem.lower()
                in {"cmd", "powershell", "pwsh", "sh", "bash"}
                or any(
                    arg.lower() in {"-c", "-command", "/c", "-encodedcommand"}
                    for arg in profile.argv
                )
            ):
                raise RuntimeFailure("target_not_allowed")
            return profile
        profiles = [
            p
            for p in self._targets.http_profiles
            if p.tenant_id == registration.tenant_id and p.target_ref == connection.target_ref
        ]
        if len(profiles) != 1:
            raise RuntimeFailure("target_not_allowed")
        profile = profiles[0]
        parsed = urlsplit(profile.url)
        try:
            ipaddress.ip_address(parsed.hostname or "")
            parsed.port
        except ValueError:
            raise RuntimeFailure("unsupported_target") from None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeFailure("target_not_allowed")
        if profile.synthetic_loopback_http:
            if (
                registration.data_origin != "SYNTHETIC"
                or parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or parsed.path != "/mcp"
            ):
                raise RuntimeFailure("target_not_allowed")
        elif parsed.scheme != "https":
            raise RuntimeFailure("target_not_allowed")
        return profile

    async def _cancel(self, session, pending):
        for request_id in tuple(pending):
            try:
                with anyio.move_on_after(0.5, shield=True):
                    await session.send_notification(
                        types.ClientNotification(
                            types.CancelledNotification(
                                params=types.CancelledNotificationParams(
                                    requestId=request_id, reason="host_cancelled"
                                )
                            )
                        )
                    )
            except Exception:
                pass

    async def _run_guarded(self, awaitable, lease, session, pending):
        operation = asyncio.create_task(awaitable)

        async def watch():
            while True:
                await asyncio.sleep(0.1)
                await self._guard.assert_current(lease)

        monitor = asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait((operation, monitor), return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor
            return await operation
        except BaseException:
            await self._cancel(session, pending)
            raise
        finally:
            operation.cancel()
            monitor.cancel()
            await asyncio.gather(operation, monitor, return_exceptions=True)
            pending.clear()

    async def discover(self, admin, registration, lease):
        # The owner keeps SDK task-group entry/exit in the same task. Shielding
        # this owner permits a bounded cleanup even if a caller cancels repeatedly.
        owner = asyncio.create_task(self._discover(admin, registration, lease))
        try:
            return await asyncio.shield(owner)
        except asyncio.CancelledError:
            if not owner.done():
                self._cancelled_owners.add(owner)
                if owner not in self._cleaning:
                    owner.cancel()
            while not owner.done():
                try:
                    await asyncio.shield(owner)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not owner.cancelled():
                owner.exception()
            self._cancelled_owners.discard(owner)
            raise

    async def _discover(self, admin, registration, lease):
        """Initialize and list tools only. No session or callable handle escapes."""
        # Authorization precedes profile lookup, credentials, guard storage, and IO.
        try:
            await _maybe_await(self._guard.authorize(admin, registration.tenant_id, "discover"))
        except Exception:
            raise RuntimeFailure("access_denied") from None
        if self._closed:
            raise RuntimeFailure("invalid_configuration")
        if (
            lease.tenant_id != registration.tenant_id
            or lease.service_id != registration.service_id
            or lease.target_policy_version != self._targets.policy_version
        ):
            raise RuntimeFailure("stale_generation")
        task = asyncio.current_task()
        log_token = _OWNED_LOG.set(True)
        self._active.add(task)
        stack, pending, session, transport = AsyncExitStack(), set(), None, None
        error, result, phase = None, None, "initialize_failed"
        try:
            async with asyncio.timeout(20):
                await self._guard.assert_current(lease)
                profile = self._profile(registration)
                secret = None
                if registration.connection.credential_ref is not None:
                    try:
                        secret, generation = await _maybe_await(
                            self._credentials.resolve(
                                registration.tenant_id, registration.connection.credential_ref
                            )
                        )
                    except Exception:
                        raise RuntimeFailure("credential_unavailable") from None
                    if (
                        not isinstance(secret, SecretStr)
                        or generation != lease.credential_generation
                    ):
                        raise RuntimeFailure("credential_unavailable")
                async with asyncio.timeout(5):
                    if isinstance(profile, ExecutableProfile):
                        env = dict(profile.env)
                        env["PYTHONIOENCODING"] = "utf-8"
                        if secret is not None:
                            if not profile.credential_env:
                                raise RuntimeFailure("credential_unavailable")
                            env[profile.credential_env] = secret.get_secret_value()
                        # DEVNULL drops all remote stderr, including secrets, with zero retention.
                        sink = stack.enter_context(open(os.devnull, "w"))
                        read, write = await stack.enter_async_context(
                            stdio_client(
                                StdioServerParameters(
                                    command=profile.executable,
                                    args=list(profile.argv),
                                    cwd=profile.cwd,
                                    env=env,
                                ),
                                errlog=sink,
                            )
                        )
                    else:
                        headers = (
                            {}
                            if secret is None
                            else {"Authorization": "Bearer " + secret.get_secret_value()}
                        )
                        transport = _ExactTargetTransport(profile.url)
                        client = await stack.enter_async_context(
                            httpx.AsyncClient(
                                transport=transport,
                                headers=headers,
                                trust_env=False,
                                follow_redirects=False,
                                timeout=5,
                            )
                        )
                        read, write, _ = await stack.enter_async_context(
                            streamable_http_client(
                                profile.url, http_client=client, terminate_on_close=True
                            )
                        )
                    session = await stack.enter_async_context(
                        ClientSession(
                            read,
                            _TrackingStream(write, pending),
                            read_timeout_seconds=timedelta(seconds=10),
                            sampling_callback=_reject,
                            elicitation_callback=_reject,
                            list_roots_callback=_reject,
                            logging_callback=_discard_log,
                        )
                    )
                    info = await self._run_guarded(session.initialize(), lease, session, pending)
                phase = "discovery_incomplete"
                from anlan.tools.dynamic_mcp.catalog import make_discovery, sanitize_tool

                tools, cursor, cursors, names = [], None, set(), set()
                async with asyncio.timeout(10):
                    for _ in range(10):
                        page = await self._run_guarded(
                            session.list_tools(cursor=cursor), lease, session, pending
                        )
                        if len(tools) + len(page.tools) > 50:
                            raise RuntimeFailure("oversized_result")
                        for tool in page.tools:
                            if tool.name in names:
                                raise RuntimeFailure("discovery_incomplete")
                            names.add(tool.name)
                            tools.append(
                                sanitize_tool(tool.name, tool.inputSchema, tool.outputSchema)
                            )
                        cursor = page.nextCursor
                        if cursor is None:
                            break
                        if cursor in cursors:
                            raise RuntimeFailure("discovery_incomplete")
                        cursors.add(cursor)
                    else:
                        raise RuntimeFailure("discovery_incomplete")
                await self._guard.assert_current(lease)
                if registration.connection.credential_ref is not None:
                    try:
                        _, generation = await _maybe_await(
                            self._credentials.resolve(
                                registration.tenant_id, registration.connection.credential_ref
                            )
                        )
                    except Exception:
                        raise RuntimeFailure("credential_unavailable") from None
                    if generation != lease.credential_generation:
                        raise RuntimeFailure("stale_generation")
                result = make_discovery(
                    discovery_id=uuid4().hex,
                    captured_generation=lease.generation,
                    protocol_version=info.protocolVersion,
                    server_name="remote-server",
                    server_version="remote-version",
                    discovered_at=self._clock(),
                    tools=tuple(tools),
                )
        except asyncio.CancelledError as exc:
            error = exc
            if session is not None:
                await self._cancel(session, pending)
        except TimeoutError:
            code = "connect_timeout" if phase == "initialize_failed" else "discovery_timeout"
            error = RuntimeFailure(transport.failure if transport and transport.failure else code)
            if session is not None:
                await self._cancel(session, pending)
        except Exception as exc:
            error = RuntimeFailure(_exception_code(exc, phase))
        finally:
            self._cleaning.add(task)
            try:
                async with asyncio.timeout(8):
                    await stack.aclose()
            except Exception as cleanup_error:
                operation_code = _exception_code(cleanup_error, None)
                if operation_code is not None:
                    if error is None or (
                        isinstance(error, asyncio.CancelledError)
                        and task not in self._cancelled_owners
                    ):
                        error = RuntimeFailure(operation_code)
                else:
                    self._cleanup_failed = True
                    if isinstance(error, RuntimeFailure):
                        error.cleanup_status = "cleanup_failed"
                    elif not isinstance(error, asyncio.CancelledError):
                        error = RuntimeFailure("cleanup_failed", "cleanup_failed")
            self._active.discard(task)
            self._cleaning.discard(task)
            _OWNED_LOG.reset(log_token)
        if (
            transport
            and transport.failure
            and not (isinstance(error, asyncio.CancelledError) and task in self._cancelled_owners)
        ):
            error = RuntimeFailure(
                transport.failure, "cleanup_failed" if self._cleanup_failed else "closed"
            )
        if error is not None:
            raise error from None
        try:
            await _maybe_await(self._guard.authorize(admin, registration.tenant_id, "discover"))
            await self._guard.assert_current(lease)
            if lease.target_policy_version != self._targets.policy_version:
                raise RuntimeFailure("stale_generation")
        except Exception as exc:
            raise RuntimeFailure(_exception_code(exc, "storage_unavailable")) from None
        return result

    async def close(self):
        self._closed = True
        tasks = tuple(task for task in self._active if task is not asyncio.current_task())
        for task in tasks:
            self._cancelled_owners.add(task)
            if task not in self._cleaning:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._cancelled_owners.difference_update(tasks)
        return CleanupReceipt("cleanup_failed" if self._cleanup_failed else "closed")

# This private scope is shared by the Executor adapter; RuntimeManager's public
# API deliberately remains discover/close. No host callback can receive sessions.


class _BusinessTrackingStream(_TrackingStream):
    def __init__(self, stream, pending, before_call):
        super().__init__(stream, pending)
        self._before_call = before_call

    async def send(self, message):
        request = message.message.root
        if isinstance(request, types.JSONRPCRequest) and request.method == "tools/call":
            await self._before_call()
            self._pending.add(request.id)
            await self._stream.send(message)
            return
        await super().send(message)


@asynccontextmanager
async def _business_session(manager, registration, lease, before_call):
    """Private transport scope with the same target, credentials and HTTP limits."""
    stack, pending, session = AsyncExitStack(), set(), None
    transport, error = None, None
    token = _OWNED_LOG.set(True)
    try:
        profile = manager._profile(registration)
        secret = None
        if registration.connection.credential_ref is not None:
            secret, generation = await _maybe_await(
                manager._credentials.resolve(
                    registration.tenant_id, registration.connection.credential_ref
                )
            )
            if not isinstance(secret, SecretStr) or generation != lease.credential_generation:
                raise RuntimeFailure("credential_unavailable")
        if isinstance(profile, ExecutableProfile):
            env = dict(profile.env)
            env["PYTHONIOENCODING"] = "utf-8"
            if secret is not None:
                if not profile.credential_env:
                    raise RuntimeFailure("credential_unavailable")
                env[profile.credential_env] = secret.get_secret_value()
            sink = stack.enter_context(open(os.devnull, "w"))
            read, write = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=profile.executable,
                        args=list(profile.argv),
                        cwd=profile.cwd,
                        env=env,
                    ),
                    errlog=sink,
                )
            )
        else:
            transport = _ExactTargetTransport(profile.url)
            headers = (
                {} if secret is None else {"Authorization": "Bearer " + secret.get_secret_value()}
            )
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=transport,
                    headers=headers,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=5,
                )
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(profile.url, http_client=client, terminate_on_close=True)
            )
        session = await stack.enter_async_context(
            ClientSession(
                read,
                _BusinessTrackingStream(write, pending, before_call),
                read_timeout_seconds=timedelta(seconds=5),
                sampling_callback=_reject,
                elicitation_callback=_reject,
                list_roots_callback=_reject,
                logging_callback=_discard_log,
            )
        )
        yield session, pending
    except BaseException as exc:
        error = exc
        if session is not None:
            await manager._cancel(session, pending)
        raise
    finally:
        try:
            async with asyncio.timeout(3):
                await stack.aclose()
        except BaseException:
            if error is None:
                raise
        finally:
            _OWNED_LOG.reset(token)
        if transport and transport.failure:
            raise RuntimeFailure(transport.failure)
