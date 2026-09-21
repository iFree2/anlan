"""Real PostgreSQL integration. Explicit test DSN required; never substitute an in-memory DB."""

import asyncio
import json
import os
import subprocess
import sys

import psycopg
import pytest

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity
from anlan.interfaces.cli import DEMO_FIELDS, DEMO_PATCHES
from anlan.workflows.material_analysis import Analysis, OfflineAnalyzer

pytestmark = pytest.mark.postgres
OWNER = Identity(tenant_id="synthetic-pg-tests", user_id="owner")


def run(coroutine):
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


@pytest.fixture(scope="module")
def dsn():
    value = os.environ.get("ANLAN_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set ANLAN_TEST_DATABASE_URL to an isolated synthetic development database")
    from anlan.infrastructure.postgres import initialize_database
    try:
        run(initialize_database(value))
    except psycopg.Error:
        pass
    else:
        return value
    # 离开except后再失败，避免原异常通过__context__泄漏配置文本。
    pytest.fail("PostgreSQL测试库未就绪；请检查本地服务、配置和权限。连接详情已隐藏。",
                pytrace=False)


def test_reconnect_preserves_ownership_material_and_idempotency(dsn):
    from anlan.interfaces.runtime import postgres_service

    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            first = await service.start(OWNER, DEMO_FIELDS)
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.get(OWNER, first["task_id"]) == first
            second = await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0],
                                          request_id="stable")
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0],
                                        request_id="stable") == second
            with pytest.raises(InvalidTransition, match="request_id"):
                await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[1],
                                     request_id="stable")
            with pytest.raises(InvalidTransition):
                await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[1],
                                     request_id="stale")
            for other in [Identity(tenant_id="other", user_id="owner"),
                          Identity(tenant_id=OWNER.tenant_id, user_id="other")]:
                with pytest.raises(AccessDenied):
                    await service.get(other, first["task_id"])
                with pytest.raises(AccessDenied):
                    await service.resume(other, first["task_id"], 2, DEMO_PATCHES[1])
            final = await service.resume(OWNER, first["task_id"], 2, DEMO_PATCHES[1],
                                         request_id="method")
            assert final["revision"] == 3
            assert final["status"] == "awaiting_review"
            assert final["fields"]["work_object_description"] == DEMO_FIELDS[
                "work_object_description"]
            assert len(await service.history(OWNER, first["task_id"])) == 3
    run(scenario())


def test_incomplete_analysis_recovers_on_new_connection_without_second_merge(dsn):
    from anlan.interfaces.runtime import postgres_service

    class FailingAnalyzer:
        async def analyze(self, application):
            raise RuntimeError("injected application failure")

    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            first = await service.start(OWNER, DEMO_FIELDS)
        async with postgres_service(dsn, FailingAnalyzer()) as service:
            with pytest.raises(RuntimeError):
                await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0],
                                     request_id="interrupted")
            interrupted = await service.get(OWNER, first["task_id"])
            assert interrupted["revision"] == 2
            assert (await service.history(OWNER, first["task_id"]))[-1]["status"] == "pending"
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            result = await service.recover(OWNER, first["task_id"])
            assert result["revision"] == 2
            assert result["run_id"] == interrupted["run_id"]
            assert result["fields"] == interrupted["fields"]
            assert result["status"] == "waiting_input"
            assert (await service.history(OWNER, first["task_id"]))[-1]["status"] == "completed"
    run(scenario())


def test_pending_submission_before_graph_execution_is_recoverable(dsn, monkeypatch):
    from anlan.interfaces.runtime import postgres_service

    async def crash(*args, **kwargs):
        raise RuntimeError("crash before graph starts")

    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            first = await service.start(OWNER, DEMO_FIELDS)
            with monkeypatch.context() as context:
                context.setattr(service._graph, "ainvoke", crash)
                with pytest.raises(RuntimeError):
                    await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0],
                                         request_id="before")
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            recovered = await service.recover(OWNER, first["task_id"])
            assert recovered["revision"] == 2
            assert recovered["fields"]["work_location_description"] == DEMO_PATCHES[0][
                "work_location_description"]
    run(scenario())


def test_mode_mismatch_does_not_mutate_task(dsn):
    from anlan.interfaces.runtime import postgres_service

    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            first = await service.start(OWNER, DEMO_FIELDS)
        async with postgres_service(dsn, OfflineAnalyzer(), mode="deepseek") as service:
            with pytest.raises(InvalidTransition, match="mode"):
                await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0])
            assert await service.get(OWNER, first["task_id"]) == first
    run(scenario())


def test_two_database_connections_cannot_execute_same_task_concurrently(dsn):
    from anlan.interfaces.runtime import postgres_service

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class BlockingAnalyzer:
            async def analyze(self, application):
                started.set()
                await release.wait()
                return Analysis(semantic_status="checked")

        async with postgres_service(dsn, OfflineAnalyzer()) as seed:
            first = await seed.start(OWNER, DEMO_FIELDS)
        async with postgres_service(dsn, BlockingAnalyzer()) as a:
            async with postgres_service(dsn, OfflineAnalyzer()) as b:
                operation = asyncio.create_task(a.resume(
                    OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="a"))
                await asyncio.wait_for(started.wait(), timeout=5)
                try:
                    with pytest.raises(TaskBusy):
                        await b.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="b")
                finally:
                    release.set()
                    await operation
                assert (await b.get(OWNER, first["task_id"]))["revision"] == 2
    run(scenario())


def test_cli_restart_and_duplicate_request(dsn, tmp_path):
    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "anlan", *args, "--trace", str(tmp_path / "trace.jsonl")],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, "ANLAN_DATABASE_URL": dsn, "PYTHONUTF8": "1"},
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    first = cli("start")
    task = first["task_id"]
    assert cli("show", "--task", task)["fields"] == first["fields"]
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps(DEMO_PATCHES[0]), encoding="utf-8")
    args = ("resume", "--task", task, "--revision", "1", "--request-id", "cli-1",
            "--fields-file", str(patch))
    second = cli(*args)
    assert second["revision"] == 2
    assert cli(*args)["run_id"] == second["run_id"]
    assert len(cli("history", "--task", task)["operations"]) == 2


def test_hard_process_exit_after_material_merge_can_recover(dsn):
    from anlan.interfaces.runtime import postgres_service

    async def seed():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            return await service.start(OWNER, DEMO_FIELDS)

    first = run(seed())
    script = """
import asyncio, os
from anlan.interfaces.runtime import postgres_service
from anlan.common.models import Identity
from anlan.interfaces.cli import DEMO_PATCHES
class ExitAnalyzer:
    async def analyze(self, application):
        os._exit(31)
async def main():
    async with postgres_service(os.environ['ANLAN_TEST_DATABASE_URL'], ExitAnalyzer()) as service:
        await service.resume(Identity(tenant_id='synthetic-pg-tests', user_id='owner'),
                             os.environ['ANLAN_CRASH_TASK'], 1, DEMO_PATCHES[0],
                             request_id='hard-exit')
asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=30,
        env={**os.environ, "ANLAN_TEST_DATABASE_URL": dsn, "ANLAN_CRASH_TASK": first["task_id"],
             "PYTHONUTF8": "1"},
    )
    assert crashed.returncode == 31

    async def recover():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            before = await service.get(OWNER, first["task_id"])
            assert before["revision"] == 2
            assert before["status"] == "analyzing"
            result = await service.recover(OWNER, first["task_id"])
            assert result["revision"] == 2
            assert result["run_id"] == before["run_id"]
            assert result["fields"] == before["fields"]
            assert result["status"] == "waiting_input"
    run(recover())


def test_lost_completion_receipt_recovers_without_running_analyzer_again(dsn, monkeypatch):
    from anlan.interfaces.runtime import postgres_service

    class MustNotRun:
        async def analyze(self, application):
            raise AssertionError("already-checkpointed analysis must not run again")

    async def crash(*args, **kwargs):
        raise RuntimeError("receipt write interrupted")

    async def scenario():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            first = await service.start(OWNER, DEMO_FIELDS)
            with monkeypatch.context() as context:
                context.setattr(service._registry, "complete", crash)
                with pytest.raises(RuntimeError):
                    await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0],
                                         request_id="receipt")
        async with postgres_service(dsn, MustNotRun()) as service:
            state = await service.recover(OWNER, first["task_id"])
            assert state["revision"] == 2
            assert state["status"] == "waiting_input"
            assert await service.resume(OWNER, first["task_id"], 1, DEMO_PATCHES[0],
                                        request_id="receipt") == state
    run(scenario())


def test_lost_lock_connection_cannot_overwrite_newer_checkpoint(dsn):
    from anlan.interfaces.runtime import postgres_service

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class OldAnalyzer:
            async def analyze(self, application):
                started.set()
                await release.wait()
                return Analysis(semantic_status="checked")

        async with postgres_service(dsn, OfflineAnalyzer()) as seed:
            first = await seed.start(OWNER, DEMO_FIELDS)
        async with postgres_service(dsn, OldAnalyzer()) as old:
            operation = asyncio.create_task(old.resume(
                OWNER, first["task_id"], 1, DEMO_PATCHES[0], request_id="old"))
            await asyncio.wait_for(started.wait(), timeout=5)
            await old._registry.conn.close()  # Server releases the session advisory lock.
            try:
                async with postgres_service(dsn, OfflineAnalyzer()) as newer:
                    recovered = await newer.recover(OWNER, first["task_id"])
                    assert recovered["revision"] == 2
                    final = await newer.resume(OWNER, first["task_id"], 2, DEMO_PATCHES[1],
                                               request_id="newer")
                    assert final["revision"] == 3
            finally:
                release.set()
                with pytest.raises(psycopg.Error):
                    await operation
        async with postgres_service(dsn, OfflineAnalyzer()) as reader:
            assert await reader.get(OWNER, first["task_id"]) == final
    run(scenario())


def test_initial_hard_exit_emits_task_receipt_before_analysis(dsn):
    script = """
import os, sys
from anlan.interfaces import cli
class ExitAnalyzer:
    async def analyze(self, application):
        os._exit(32)
cli.OfflineAnalyzer = ExitAnalyzer
sys.argv = ['anlan', 'start']
cli.main()
"""
    environment = {**os.environ, "ANLAN_DATABASE_URL": dsn, "PYTHONUTF8": "1"}
    crashed = subprocess.run([sys.executable, "-c", script], capture_output=True,
                             text=True, encoding="utf-8", timeout=30, env=environment)
    assert crashed.returncode == 32
    receipt = json.loads(crashed.stderr.strip())
    assert receipt["event"] == "task_created"
    recovered = subprocess.run(
        [sys.executable, "-m", "anlan", "recover", "--task", receipt["task_id"]],
        capture_output=True, text=True, encoding="utf-8", timeout=30, env=environment,
    )
    assert recovered.returncode == 0, recovered.stderr
    state = json.loads(recovered.stdout)
    assert state["revision"] == 1
    assert state["status"] == "waiting_input"


def test_cli_process_is_rejected_while_another_process_holds_task_lock(dsn):
    from anlan.interfaces.runtime import postgres_service

    async def seed():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            return await service.start(OWNER, DEMO_FIELDS)

    first = run(seed())
    with psycopg.connect(dsn, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (first["task_id"],))
        other = subprocess.run(
            [sys.executable, "-m", "anlan", "resume", "--task", first["task_id"],
             "--revision", "1", "--request-id", "competing-process",
             "--tenant", OWNER.tenant_id, "--user", OWNER.user_id,
             "--fields-file", "examples/synthetic/location.json"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, "ANLAN_DATABASE_URL": dsn, "PYTHONUTF8": "1"},
        )
        assert other.returncode == 2
        assert "正在其他进程执行" in other.stderr

    async def verify():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.get(OWNER, first["task_id"]) == first
    run(verify())
