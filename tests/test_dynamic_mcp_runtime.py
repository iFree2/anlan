"""Actual SDK transport tests against fixed synthetic processes and sockets."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from anlan.tools.dynamic_mcp import runtime

FIXTURE = str(Path(__file__).parent.joinpath("fixtures/dynamic_mcp_server.py").resolve())


class Guard:
    current = True

    def authorize(self, admin, tenant, action):
        if admin != "admin" or tenant != "tenant":
            raise ValueError("access_denied")

    async def assert_current(self, lease):
        if not self.current:
            raise ValueError("stale_generation")


class Credentials:
    calls = []

    async def resolve(self, tenant, ref):
        self.calls.append((tenant, ref))
        return SecretStr("CREDENTIAL_SENTINEL"), "1"


def setup(tmp_path, mode="normal", http_url=None):
    log = tmp_path / "events.jsonl"
    args = (FIXTURE, mode, str(log))
    profiles = (
        runtime.ExecutableProfile("tenant", "fixture", sys.executable, args, str(Path.cwd())),
    )
    targets = runtime.TrustedTargets(
        "1",
        profiles,
        ()
        if not http_url
        else (runtime.HttpProfile("tenant", "fixture", http_url, synthetic_loopback_http=True),),
    )
    connection = (
        SimpleNamespace(
            transport="stdio", executable_ref="fixture", argv=list(args), credential_ref=None
        )
        if not http_url
        else SimpleNamespace(transport="streamable_http", target_ref="fixture", credential_ref=None)
    )
    registration = SimpleNamespace(
        tenant_id="tenant", service_id="service", connection=connection, data_origin="SYNTHETIC"
    )
    lease = SimpleNamespace(
        tenant_id="tenant",
        service_id="service",
        generation=1,
        config_revision=1,
        target_policy_version="1",
        credential_generation="1",
    )
    guard = Guard()
    return runtime.RuntimeManager(targets, Credentials(), guard), registration, lease, log, guard


def events(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def pid_exited(pid):
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return True
        try:
            return kernel.WaitForSingleObject(ctypes.c_void_p(handle), 1000) == 0
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))

    deadline = time.monotonic() + 1
    while True:
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            # SDK may already have reaped its child; probe existence without a signal.
            # This path is POSIX-only: Windows os.kill(pid, 0) is not a safe probe.
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
        else:
            if reaped == pid:
                return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


async def test_official_stdio_pagination_redaction_and_owned_pid_exit(tmp_path):
    manager, registration, lease, log, _ = setup(tmp_path)
    result = await manager.discover("admin", registration, lease)
    assert [tool.name for tool in result.tools] == ["synthetic_one", "synthetic_two"]
    assert "REMOTE_SECRET" not in repr(result)
    wire = events(log)
    assert [item["method"] for item in wire if item.get("method") == "tools/list"] == [
        "tools/list"
    ] * 2
    assert not any(item.get("method") == "tools/call" for item in wire)
    assert pid_exited(wire[0]["pid"])
    assert (await manager.close()).status == "closed"


async def test_denied_and_argv_replacement_never_spawn(tmp_path):
    manager, registration, lease, log, _ = setup(tmp_path)
    with pytest.raises(runtime.RuntimeFailure, match="access_denied"):
        await manager.discover("ordinary", registration, lease)
    registration.connection.argv.append("untrusted")
    with pytest.raises(runtime.RuntimeFailure, match="target_not_allowed"):
        await manager.discover("admin", registration, lease)
    assert not log.exists()


async def test_cancel_uses_actual_wire_id_and_exits_process(tmp_path):
    manager, registration, lease, log, _ = setup(tmp_path, "slow")
    task = asyncio.create_task(manager.discover("admin", registration, lease))
    for _ in range(200):
        if log.exists() and any(e.get("method") == "tools/list" for e in events(log)):
            break
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    wire = events(log)
    request_id = next(e["request_id"] for e in wire if e.get("method") == "tools/list")
    assert any(e.get("cancelled_id") == request_id for e in wire)
    assert pid_exited(wire[0]["pid"])


async def test_real_http_session_delete_and_no_production_call(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server_log = tmp_path / "server.jsonl"
    process = subprocess.Popen(
        [sys.executable, FIXTURE, "http", str(server_log), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(200):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                    break
            except OSError:
                await asyncio.sleep(0.02)
        manager, registration, lease, _, _ = setup(
            tmp_path, http_url=f"http://127.0.0.1:{port}/mcp"
        )
        result = await manager.discover("admin", registration, lease)
        assert len(result.tools) == 2
        wire = events(server_log)
        assert any(e.get("method") == "DELETE" for e in wire)
        assert not any(e.get("method") == "tools/call" for e in wire)
        # A separate, test-owned official SDK session exercises only fixed fake data.
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with httpx.AsyncClient(trust_env=False) as client:
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
                    result = await session.call_tool("synthetic_one", {})
                    assert result.structuredContent == {"synthetic": True}
    finally:
        process.terminate()
        process.wait(timeout=8)


async def test_disable_during_discovery_cancels_actual_request(tmp_path):
    manager, registration, lease, log, guard = setup(tmp_path, "slow")
    task = asyncio.create_task(manager.discover("admin", registration, lease))
    for _ in range(200):
        if log.exists() and any(e.get("method") == "tools/list" for e in events(log)):
            break
        await asyncio.sleep(0.02)
    guard.current = False
    with pytest.raises(runtime.RuntimeFailure, match="stale_generation"):
        await asyncio.wait_for(task, 10)
    wire = events(log)
    assert any(e.get("method") == "notifications/cancelled" for e in wire)
    assert pid_exited(wire[0]["pid"])


async def test_only_test_code_can_call_fixed_synthetic_fixture(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    log = tmp_path / "call.jsonl"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[FIXTURE, "normal", str(log)],
        env={"PYTHONIOENCODING": "utf-8"},
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("synthetic_one", {})
            assert result.structuredContent == {"synthetic": True}
    assert any(e.get("method") == "tools/call" for e in events(log))
    assert not hasattr(runtime.RuntimeManager, "call")
    assert not hasattr(runtime.RuntimeManager, "diagnose")


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/mcp",
        "http://127.0.0.2/mcp",
        "http://127.0.0.1/wrong",
        "http://127.0.0.1/mcp?q=x",
    ],
)
async def test_unapproved_http_target_never_resolves_credentials(tmp_path, url):
    manager, registration, lease, _, _ = setup(tmp_path, http_url=url)
    registration.connection.credential_ref = "credential"
    before = len(Credentials.calls)
    with pytest.raises(runtime.RuntimeFailure):
        await manager.discover("admin", registration, lease)
    assert len(Credentials.calls) == before


async def test_sdk_debug_logs_never_retain_remote_descriptions(tmp_path, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    manager, registration, lease, _, _ = setup(tmp_path)
    await manager.discover("admin", registration, lease)
    assert "REMOTE_SECRET" not in caplog.text


async def test_trusted_registry_error_code_survives_runtime_boundary(tmp_path):
    from anlan.tools.dynamic_mcp.registry import RegistryError

    manager, registration, lease, log, guard = setup(tmp_path)

    async def stale(_lease):
        raise RegistryError("stale_generation")

    guard.assert_current = stale
    with pytest.raises(runtime.RuntimeFailure, match="stale_generation"):
        await manager.discover("admin", registration, lease)
    assert not log.exists()


async def test_rotated_credential_rejects_late_discovery(tmp_path):
    manager, registration, lease, _, _ = setup(tmp_path)
    registration.connection.credential_ref = "ref"
    # Host profile explicitly controls the environment destination.
    from dataclasses import replace

    manager._targets = replace(
        manager._targets,
        executable_profiles=(
            replace(manager._targets.executable_profiles[0], credential_env="FIXTURE_TOKEN"),
        ),
    )

    class Rotating:
        count = 0

        async def resolve(self, tenant, ref):
            self.count += 1
            return SecretStr("CREDENTIAL_SENTINEL"), "1" if self.count == 1 else "2"

    manager._credentials = Rotating()
    with pytest.raises(runtime.RuntimeFailure, match="stale_generation"):
        await manager.discover("admin", registration, lease)


async def test_actual_stdio_disconnect_is_classified_and_cleaned(tmp_path):
    manager, registration, lease, log, _ = setup(tmp_path, "disconnect")
    with pytest.raises(runtime.RuntimeFailure, match="disconnected"):
        await manager.discover("admin", registration, lease)
    assert pid_exited(events(log)[0]["pid"])


async def test_repeated_caller_cancel_cannot_interrupt_owned_cleanup(tmp_path):
    manager, registration, lease, log, _ = setup(tmp_path, "slow")
    task = asyncio.create_task(manager.discover("admin", registration, lease))
    for _ in range(200):
        if log.exists() and any(e.get("method") == "tools/list" for e in events(log)):
            break
        await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    assert pid_exited(events(log)[0]["pid"])
    assert (await manager.close()).status == "closed"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("bad_ref", "schema_unsupported"),
        ("oversize", "oversized_result"),
        ("duplicate", "discovery_incomplete"),
    ],
)
async def test_real_sdk_untrusted_schema_or_duplicate_rejected_and_closed(tmp_path, mode, code):
    manager, registration, lease, log, _ = setup(tmp_path, mode)
    with pytest.raises(runtime.RuntimeFailure, match=code):
        await manager.discover("admin", registration, lease)
    assert pid_exited(events(log)[0]["pid"])


@pytest.mark.parametrize("cross_origin", [False, True])
async def test_real_http_redirect_is_rejected_before_second_request(tmp_path, cross_origin, caplog):
    import logging
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    caplog.set_level(logging.DEBUG)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.path)
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.2:1/mcp" if cross_origin else "/stolen")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        manager, registration, lease, _, _ = setup(
            tmp_path, http_url=f"http://127.0.0.1:{server.server_port}/mcp"
        )
        registration.connection.credential_ref = "ref"
        with pytest.raises(runtime.RuntimeFailure, match="target_not_allowed"):
            await manager.discover("admin", registration, lease)
        assert requests == ["/mcp"]
        assert "CREDENTIAL_SENTINEL" not in caplog.text
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream", "gzip"])
async def test_real_http_oversized_stream_rejected_before_parse(tmp_path, content_type):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/json" if content_type == "gzip" else content_type
            )
            body = b'{"oversized":"' + b"x" * (600 * 1024) + b'"}'
            if content_type == "gzip":
                import gzip

                body = gzip.compress(body)
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            if content_type == "text/event-stream":
                body = b"event: message\ndata: " + body + b"\n\n"
            try:
                self.wfile.write(body)
            except (ConnectionResetError, BrokenPipeError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        manager, registration, lease, _, _ = setup(
            tmp_path, http_url=f"http://127.0.0.1:{server.server_port}/mcp"
        )
        with pytest.raises(runtime.RuntimeFailure, match="oversized_result"):
            await manager.discover("admin", registration, lease)
        assert (await manager.close()).status == "closed"
    finally:
        server.shutdown()
        server.server_close()


async def test_host_authorization_revoked_before_result_never_returns_snapshot(tmp_path):
    manager, registration, lease, _, guard = setup(tmp_path)
    initial = guard.authorize
    calls = 0

    def revoked(admin, tenant, action):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError("access_denied")
        initial(admin, tenant, action)

    guard.authorize = revoked
    with pytest.raises(runtime.RuntimeFailure, match="access_denied"):
        await manager.discover("admin", registration, lease)


@pytest.fixture
def posix_pid_probe(monkeypatch):
    """Exercise POSIX decisions without invoking Windows kill or requiring Linux."""
    import ctypes

    calls = []
    elapsed = [0.0]
    simulated_os = SimpleNamespace(WNOHANG=1)

    def sleep(seconds):
        calls.append(("sleep", seconds))
        elapsed[0] += seconds

    monkeypatch.setitem(pid_exited.__globals__, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setitem(pid_exited.__globals__, "os", simulated_os)
    monkeypatch.setitem(
        pid_exited.__globals__, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=sleep)
    )
    # Linux has no ctypes.windll. Reproduce that constraint on the Windows host.
    monkeypatch.delattr(ctypes, "windll", raising=False)
    return simulated_os, calls, elapsed


def test_pid_probe_posix_reaps_exited_child(posix_pid_probe):
    simulated_os, calls, _ = posix_pid_probe

    def waitpid(pid, flags):
        calls.append(("waitpid", pid, flags))
        return pid, 0

    simulated_os.waitpid = waitpid
    simulated_os.kill = lambda *_: pytest.fail("reaped child needs no existence probe")
    assert pid_exited(424242)
    assert calls == [("waitpid", 424242, simulated_os.WNOHANG)]


def test_pid_probe_posix_missing_nonchild_is_exited(posix_pid_probe):
    simulated_os, calls, _ = posix_pid_probe

    def waitpid(pid, flags):
        raise ChildProcessError

    def kill(pid, signal):
        calls.append(("kill", pid, signal))
        raise ProcessLookupError

    simulated_os.waitpid, simulated_os.kill = waitpid, kill
    assert pid_exited(424242)
    assert calls == [("kill", 424242, 0)]


@pytest.mark.parametrize("child", [True, False])
def test_pid_probe_posix_live_process_is_not_exited(posix_pid_probe, child):
    simulated_os, calls, elapsed = posix_pid_probe

    def waitpid(pid, flags):
        if child:
            return 0, 0
        raise ChildProcessError

    simulated_os.waitpid = waitpid
    simulated_os.kill = lambda pid, signal: calls.append(("kill", pid, signal))
    assert not pid_exited(424242)
    assert 1 <= elapsed[0] <= 1.02
    assert all(call[2] == 0 for call in calls if call[0] == "kill")


def test_pid_probe_posix_permission_denied_cannot_claim_exit(posix_pid_probe):
    simulated_os, _, _ = posix_pid_probe

    def waitpid(pid, flags):
        raise ChildProcessError

    def kill(pid, signal):
        raise PermissionError

    simulated_os.waitpid, simulated_os.kill = waitpid, kill
    assert not pid_exited(424242)


def test_pid_probe_posix_observes_nonchild_disappearing(posix_pid_probe):
    simulated_os, _, elapsed = posix_pid_probe
    probes = []

    def waitpid(pid, flags):
        raise ChildProcessError

    def kill(pid, signal):
        probes.append((pid, signal))
        if len(probes) > 1:
            raise ProcessLookupError

    simulated_os.waitpid, simulated_os.kill = waitpid, kill
    assert pid_exited(424242)
    assert probes == [(424242, 0), (424242, 0)]
    assert 0 < elapsed[0] < 1
