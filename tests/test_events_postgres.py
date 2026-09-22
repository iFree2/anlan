"""Real PG event durability, isolation, freshness and task association."""
import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from test_events import NOW, OWNER, binding, payload

from anlan.common.errors import AccessDenied, TaskBusy
from anlan.common.models import Identity
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.cli import DEMO_FIELDS, DEMO_PATCHES
from anlan.interfaces.event_runtime import process_event
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.event_contracts import EventConflict
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres


def run(coro):
    return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)


@pytest.fixture(scope="module")
def dsn():
    value = os.environ.get("ANLAN_TEST_DATABASE_URL")
    if not value:
        pytest.fail("P5 tests require explicit real PostgreSQL; no skip fallback", pytrace=False)
    run(initialize_database(value))
    run(EventStore(value).initialize())
    return value


async def setup(dsn, kind="helmet_missing", **config_changes):
    async with postgres_service(dsn, OfflineAnalyzer()) as service:
        state = await service.start(OWNER, DEMO_FIELDS)
    config = binding(state, source_id="source-" + uuid4().hex, kind=kind, **config_changes)
    store = EventStore(dsn, clock=lambda: NOW)
    return store, state, config


@pytest.mark.parametrize("kind", ["helmet_missing", "gas_abnormal"])
def test_raw_alarm_survives_disconnect_and_links_once(dsn, kind):
    async def scenario():
        store, state, config = await setup(dsn, kind)
        received = await store.receive(OWNER, config.source_id, payload(kind), config)
        assert received["admission"] == "pending" and received["result"] is None
        # Simulate no Agent or process: a fresh store can read the committed raw alarm.
        assert await EventStore(dsn).get(OWNER, received["receipt_id"]) == received
        result = await process_event(dsn, OWNER, received["receipt_id"], clock=lambda: NOW)
        assert result["result"]["status"] == "linked"
        assert result["result"]["revision"] == state["revision"]
        assert result["raw"] == payload(kind)
        assert result["raw"]["alarm_state"] == "active"
        assert await process_event(dsn, OWNER, received["receipt_id"], clock=lambda: NOW) == result
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.get(OWNER, state["task_id"]) == state
    run(scenario())


def test_duplicate_concurrency_and_conflicting_reuse(dsn):
    async def scenario():
        store, _, config = await setup(dsn)
        rows = await asyncio.gather(*[store.receive(OWNER, config.source_id, payload(), config)
                                      for _ in range(6)])
        assert len({row["receipt_id"] for row in rows}) == 1
        with pytest.raises(EventConflict):
            await store.receive(OWNER, config.source_id, payload(confidence=0.1), config)
        # Different host binding on redelivery cannot overwrite original target.
        other = config.model_copy(update={"task_id": "other"})
        assert await store.receive(OWNER, config.source_id, payload(), other) == rows[0]
    run(scenario())


@pytest.mark.parametrize(("changes", "reason"), [
    ({"object_ref": "wrong-object"}, "object_mismatch"),
    ({"observed_at": (NOW + timedelta(seconds=1)).isoformat()}, "future_event"),
    ({"observed_at": (NOW - timedelta(minutes=6)).isoformat(),
      "expires_at": (NOW - timedelta(seconds=1)).isoformat()}, "expired_event"),
])
def test_invalid_temporal_or_object_association_is_retained(dsn, changes, reason):
    async def scenario():
        store, _, config = await setup(dsn)
        row = await store.receive(OWNER, config.source_id, payload(**changes), config)
        assert row["admission"] == reason and row["raw"] == payload(**changes)
        assert (await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
                )["result"]["status"] == reason
    run(scenario())


def test_unknown_source_kind_and_cross_identity_are_not_authority(dsn):
    async def scenario():
        store, _, config = await setup(dsn)
        row = await store.receive(OWNER, "unknown-" + uuid4().hex, payload())
        assert row["admission"] == "unknown_source"
        wrong_kind = await store.receive(OWNER, config.source_id, payload("gas_abnormal"), config)
        assert wrong_kind["admission"] == "kind_mismatch"
        for stranger in [Identity(tenant_id=OWNER.tenant_id, user_id="other"),
                         Identity(tenant_id="other", user_id=OWNER.user_id)]:
            with pytest.raises(AccessDenied):
                await store.receive(stranger, config.source_id, payload(), config)
            with pytest.raises(AccessDenied):
                await store.get(stranger, row["receipt_id"])
            with pytest.raises(AccessDenied):
                await process_event(dsn, stranger, row["receipt_id"], clock=lambda: NOW)
    run(scenario())


def test_sequence_and_time_watermarks_never_regress(dsn):
    async def scenario():
        store, _, config = await setup(dsn)
        newest = await store.receive(OWNER, config.source_id, payload(sequence=3), config)
        for changes, reason in [({"sequence": 2}, "out_of_order"),
                                ({"sequence": 3}, "sequence_conflict"),
                                ({"sequence": 4, "observed_at":
                                  (NOW - timedelta(seconds=20)).isoformat()}, "out_of_order")]:
            row = await store.receive(OWNER, config.source_id,
                                      payload(event_id=uuid4().hex, **changes), config)
            assert row["admission"] == reason
        assert (await process_event(dsn, OWNER, newest["receipt_id"], clock=lambda: NOW)
                )["result"]["status"] == "linked"
    run(scenario())


def test_newer_event_stales_pending_old_event_without_changing_raw(dsn):
    async def scenario():
        store, _, config = await setup(dsn)
        old = await store.receive(OWNER, config.source_id, payload(), config)
        new = await store.receive(OWNER, config.source_id,
                                  payload(event_id="new", sequence=2), config)
        stale = await process_event(dsn, OWNER, old["receipt_id"], clock=lambda: NOW)
        assert stale["result"]["status"] == "superseded_event"
        assert stale["raw"] == old["raw"]
        assert (await process_event(dsn, OWNER, new["receipt_id"], clock=lambda: NOW)
                )["result"]["status"] == "linked"
    run(scenario())


@pytest.mark.parametrize("target", ["missing", "other_user", "other_tenant", "stale"])
def test_task_association_requires_owner_and_current_material(dsn, target):
    async def scenario():
        store, state, config = await setup(dsn)
        if target.startswith("other"):
            stranger = Identity(tenant_id=OWNER.tenant_id if target == "other_user" else "other",
                                user_id="other" if target == "other_user" else OWNER.user_id)
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                other = await service.start(stranger, DEMO_FIELDS)
            config = config.model_copy(update={"task_id": other["task_id"]})
        elif target == "missing":
            config = config.model_copy(update={"task_id": uuid4().hex})
        row = await store.receive(OWNER, config.source_id, payload(), config)
        if target == "stale":
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                await service.resume(OWNER, state["task_id"], 1, DEMO_PATCHES[0])
        result = await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
        assert result["result"]["status"] == (
            "stale_material" if target == "stale" else "task_unavailable")
        assert "fields" not in result["result"]
    run(scenario())


def test_lock_busy_and_crash_preserve_pending_receipt(dsn, monkeypatch):
    async def scenario():
        store, state, config = await setup(dsn)
        row = await store.receive(OWNER, config.source_id, payload(), config)
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            async with service._registry.locked(OWNER, state["task_id"]):
                with pytest.raises(TaskBusy):
                    await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
        async def broken(*args, **kwargs):
            raise RuntimeError("simulated association crash")
        with monkeypatch.context() as context:
            context.setattr(EventStore, "finish", broken)
            with pytest.raises(RuntimeError, match="association crash"):
                await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
        assert (await store.get(OWNER, row["receipt_id"]))["result"] is None
        assert (await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
                )["result"]["status"] == "linked"
    run(scenario())


def test_expiry_at_processing_time_does_not_erase_alarm(dsn):
    async def scenario():
        store, _, config = await setup(dsn)
        row = await store.receive(OWNER, config.source_id, payload(), config)
        result = await process_event(dsn, OWNER, row["receipt_id"],
                                     clock=lambda: NOW + timedelta(minutes=6))
        assert result["result"]["status"] == "expired_event"
        assert result["raw"]["alarm_state"] == "active"
    run(scenario())


def test_terminated_association_connection_cannot_publish_late_result(dsn, monkeypatch):
    import psycopg

    async def scenario():
        store, _, config = await setup(dsn)
        row = await store.receive(OWNER, config.source_id, payload(), config)
        original = EventStore.finish

        async def lose_connection(self, conn, *args):
            # Terminate only the connection handed to this test's association writer.
            async with await store.connect() as killer:
                cursor = await killer.execute("SELECT pg_terminate_backend(%s) AS stopped",
                                              (conn.info.backend_pid,))
                assert (await cursor.fetchone())["stopped"] is True
            return await original(self, conn, *args)

        with monkeypatch.context() as context:
            context.setattr(EventStore, "finish", lose_connection)
            with pytest.raises(psycopg.Error):
                await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
        assert (await store.get(OWNER, row["receipt_id"]))["result"] is None
        assert (await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
                )["result"]["status"] == "linked"
    run(scenario())


@pytest.mark.parametrize("change", ["contract", "pending", "run_only"])
def test_material_contract_pending_and_run_identity(dsn, change):
    from anlan.workflows.registry import Operation

    async def scenario():
        store, state, config = await setup(dsn)
        if change == "run_only":
            config = config.model_copy(update={"run_id": str(uuid4())})
        row = await store.receive(OWNER, config.source_id, payload(), config)
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            if change == "contract":
                await service._registry.conn.execute(
                    "UPDATE anlan_tasks SET contract_version='test-incompatible' WHERE task_id=%s",
                    (state["task_id"],))
            elif change == "pending":
                async with service._registry.locked(OWNER, state["task_id"]):
                    await service._registry.reserve(state["task_id"], Operation(
                        "interrupted", str(uuid4()), "resume", 1, DEMO_PATCHES[0]))
        result = await process_event(dsn, OWNER, row["receipt_id"], clock=lambda: NOW)
        assert result["result"]["status"] == {
            "contract": "material_contract_mismatch", "pending": "material_pending",
            "run_only": "stale_material"}[change]
    run(scenario())
