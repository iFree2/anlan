"""Shared call reservations use isolated authorization IDs in real PostgreSQL."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest


def run(coroutine):
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def test_budget_module_exists():
    assert importlib.util.find_spec("anlan.infrastructure.budget") is not None


@pytest.fixture
def ledger():
    from anlan.infrastructure.budget import BudgetLedger, BudgetUnavailable

    dsn = os.environ.get("ANLAN_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set ANLAN_TEST_DATABASE_URL to an isolated development database")
    value = BudgetLedger(dsn, authorization_id="test-" + uuid4().hex,
                         total_limit=3, package_limit=2)
    try:
        run(value.initialize())
    except BudgetUnavailable:
        pass
    else:
        return value
    pytest.fail("PostgreSQL测试库未就绪；连接详情已隐藏。", pytrace=False)


@pytest.mark.postgres
def test_reconnect_failed_unknown_and_new_attempts_remain_charged(ledger):
    from anlan.infrastructure.budget import BudgetExceeded, BudgetLedger

    async def scenario():
        first = await ledger.reserve("p2-wp02", "same-run")
        second = await ledger.reserve("P2-WP02", "same-run")
        assert first != second
        await ledger.finish(first, "failed", error="transport_error")
        fresh = BudgetLedger(os.environ["ANLAN_TEST_DATABASE_URL"], ledger.authorization_id,
                             total_limit=3, package_limit=2)
        await fresh.initialize()
        with pytest.raises(BudgetExceeded):
            await fresh.reserve("p2-wp02", "other-run")
        await fresh.reserve("P2-WP03", "third-run")
        with pytest.raises(BudgetExceeded):
            await fresh.reserve("P2-WP04", "fourth-run")
        snapshot = await fresh.snapshot()
        assert snapshot["total_reserved"] == 3
        assert snapshot["packages"] == {"P2-WP02": 2, "P2-WP03": 1}
        assert snapshot["status_counts"] == {"reserved": 2, "failed": 1, "succeeded": 0}
        assert snapshot["total_limit"] == 3
        assert snapshot["package_limit"] == 2
        json.dumps(snapshot)
    run(scenario())


@pytest.mark.postgres
def test_concurrent_reservations_never_exceed_package_or_total_limit(ledger):
    from anlan.infrastructure.budget import BudgetExceeded

    async def scenario():
        outcomes = await asyncio.gather(*[
            ledger.reserve("P2-WP02", f"run-{index}") for index in range(12)
        ], return_exceptions=True)
        assert sum(isinstance(value, str) for value in outcomes) == 2
        assert sum(isinstance(value, BudgetExceeded) for value in outcomes) == 10
        outcomes = await asyncio.gather(*[
            ledger.reserve(f"P2-WP{index:02d}", "next") for index in range(3, 12)
        ], return_exceptions=True)
        assert sum(isinstance(value, str) for value in outcomes) == 1
        assert sum(isinstance(value, BudgetExceeded) for value in outcomes) == 8
        assert (await ledger.snapshot())["total_reserved"] == 3
    run(scenario())


@pytest.mark.postgres
def test_initialize_never_changes_limits_or_reservations(ledger):
    from anlan.infrastructure.budget import BudgetConflict, BudgetLedger

    async def scenario():
        await ledger.reserve("P2-WP02", "run")
        changed = BudgetLedger(os.environ["ANLAN_TEST_DATABASE_URL"], ledger.authorization_id,
                               total_limit=4, package_limit=2)
        with pytest.raises(BudgetConflict):
            await changed.initialize()
        with pytest.raises(BudgetConflict):
            await changed.reserve("P2-WP02", "run")
        assert (await ledger.snapshot())["total_reserved"] == 1
    run(scenario())


@pytest.mark.postgres
def test_finish_is_idempotent_but_cannot_overwrite_or_cross_authorization(ledger):
    from anlan.infrastructure.budget import BudgetConflict, BudgetLedger

    async def scenario():
        attempt = await ledger.reserve("P2-WP02", "run")
        usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        await ledger.finish(attempt, "succeeded", usage=usage)
        await ledger.finish(attempt, "succeeded", usage=dict(usage))
        with pytest.raises(BudgetConflict):
            await ledger.finish(attempt, "failed", error="unknown_error")
        with pytest.raises(BudgetConflict):
            await ledger.finish(attempt, "succeeded", usage={"total_tokens": 4})
        other = BudgetLedger(os.environ["ANLAN_TEST_DATABASE_URL"], "test-" + uuid4().hex,
                             total_limit=1, package_limit=1)
        await other.initialize()
        with pytest.raises(BudgetConflict):
            await other.finish(attempt, "succeeded", usage=usage)
        row = (await ledger.snapshot())["attempts"][0]
        assert row["status"] == "succeeded"
        assert row["usage"] == usage
    run(scenario())


@pytest.mark.postgres
def test_hard_exit_after_reserve_keeps_unknown_attempt(ledger):
    script = """
import asyncio, os
from anlan.infrastructure.budget import BudgetLedger
async def main():
    ledger = BudgetLedger(os.environ['ANLAN_TEST_DATABASE_URL'],
                          os.environ['BUDGET_TEST_AUTH'], total_limit=3, package_limit=2)
    await ledger.reserve('P2-WP02', 'hard-exit')
    os._exit(31)
asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
"""
    process = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30,
                             env={**os.environ, "BUDGET_TEST_AUTH": ledger.authorization_id})
    assert process.returncode == 31
    snapshot = run(ledger.snapshot())
    assert snapshot["total_reserved"] == 1
    assert snapshot["attempts"][0]["status"] == "reserved"


@pytest.mark.postgres
def test_independent_processes_share_one_package_limit(ledger):
    script = """
import asyncio, os
from anlan.infrastructure.budget import BudgetLedger, BudgetExceeded
async def main():
    ledger = BudgetLedger(os.environ['ANLAN_TEST_DATABASE_URL'],
                          os.environ['BUDGET_TEST_AUTH'], total_limit=3, package_limit=2)
    outcomes = await asyncio.gather(*[
        ledger.reserve('p2-wp02', 'competing-process') for _ in range(4)
    ], return_exceptions=True)
    if any(not isinstance(value, (str, BudgetExceeded)) for value in outcomes):
        raise SystemExit(2)
    print(sum(isinstance(value, str) for value in outcomes))
asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
"""
    environment = {**os.environ, "BUDGET_TEST_AUTH": ledger.authorization_id}
    children = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=environment)
                for _ in range(2)]
    try:
        outputs = [child.communicate(timeout=40) for child in children]
        assert all(child.returncode == 0 for child in children)
        assert sum(int(stdout.strip()) for stdout, _ in outputs) == 2
        assert run(ledger.snapshot())["packages"] == {"P2-WP02": 2}
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


@pytest.mark.postgres
def test_null_usage_values_are_preserved(ledger):
    async def scenario():
        attempt = await ledger.reserve("P2-WP02", "nullable-usage")
        await ledger.finish(attempt, "succeeded", usage={"total_tokens": None})
        assert (await ledger.snapshot())["attempts"][0]["usage"] == {"total_tokens": None}
    run(scenario())


@pytest.mark.parametrize("package", ["P0-WP02", "P8-WP02", "P2-WP2", "P2-WP002",
                                     " P2-WP02", "P2-WP02\n", "garbage", None])
def test_invalid_packages_rejected_before_connecting(package):
    from anlan.infrastructure.budget import BudgetLedger
    with pytest.raises(ValueError):
        run(BudgetLedger("invalid").reserve(package, "run"))


@pytest.mark.parametrize("arguments", [
    {"status": "reserved"}, {"status": "failed", "error": "contains secret text"},
    {"status": "failed", "error": "sk-secret"},
    {"status": "succeeded", "usage": {"secret": "hidden"}},
    {"status": "succeeded", "usage": {"total_tokens": -1}},
    {"status": "succeeded", "usage": {"total_tokens": True}},
    {"status": "succeeded", "usage": {"total_tokens": 1.5}},
])
def test_invalid_finish_payload_rejected_before_connecting(arguments):
    from anlan.infrastructure.budget import BudgetLedger
    with pytest.raises(ValueError):
        run(BudgetLedger("invalid").finish(str(uuid4()), **arguments))


def test_connection_errors_do_not_reveal_dsn_or_driver_error():
    from anlan.infrastructure.budget import BudgetLedger, BudgetUnavailable
    with pytest.raises(BudgetUnavailable) as error:
        run(BudgetLedger("invalid-secret-dsn").initialize())
    assert "invalid-secret-dsn" not in str(error.value)
    assert error.value.__context__ is None


@pytest.mark.parametrize("limits", [
    {"total_limit": 0}, {"package_limit": -1}, {"total_limit": True},
    {"total_limit": 1.5}, {"package_limit": 11}, {"total_limit": 101},
])
def test_invalid_or_excessive_limits_rejected(limits):
    from anlan.infrastructure.budget import BudgetLedger
    with pytest.raises(ValueError):
        BudgetLedger("invalid", **limits)
