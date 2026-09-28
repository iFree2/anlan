import importlib.util
import subprocess

import httpx
import pytest


def module():
    spec = importlib.util.spec_from_file_location("benchmark", "scripts/benchmark_service.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


async def test_latency_measurement_retains_http_failures_timeouts_and_changed_snapshots():
    benchmark = module()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("do not expose secret-sentinel")
        if calls == 2:
            return httpx.Response(500)
        return httpx.Response(200, json={"revision": 2 if calls == 3 else 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                 base_url="http://localhost") as client:
        result = await benchmark.measure(client, "/tasks/task", {"revision": 1}, 4)
    assert len(result["samples"]) == 24
    assert result["failed"] == 3 and result["succeeded"] == 21
    assert result["p95_ms"] <= result["max_ms"]
    assert result["passed"] is False
    assert "secret-sentinel" not in str(result)


@pytest.mark.parametrize("concurrency", [0, 2, 9])
async def test_only_predeclared_small_loads_are_allowed(concurrency):
    with pytest.raises(ValueError):
        await module().measure(None, "/tasks/task", {}, concurrency)


def test_cleanup_escalates_only_owned_process_after_bounded_wait():
    class Process:
        stopped = False
        actions = []

        def poll(self):
            return 1 if self.stopped else None

        def terminate(self):
            self.actions.append("terminate")

        def wait(self, timeout):
            self.actions.append(("wait", timeout))
            if not self.stopped:
                raise subprocess.TimeoutExpired("owned-only", timeout)

        def kill(self):
            self.actions.append("kill")
            self.stopped = True

    process = Process()
    result = module().stop_owned(process)
    assert process.actions == ["terminate", ("wait", 10), "kill", ("wait", 5)]
    assert result == {"owned_process_stopped": True, "forced_stop": True}
