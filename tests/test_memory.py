"""Memory lifecycle tests use synthetic identities and real PostgreSQL."""

import asyncio
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from anlan.contracts import Identity

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
FEEDBACK = {
    "data_origin": "SYNTHETIC", "source_ref": "feedback-demo", "version": 1,
    "key": "detail_level", "value": "brief", "observed_at": NOW.isoformat(),
    "expires_at": (NOW + timedelta(days=30)).isoformat(),
}


def run(coro):
    return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)


def test_memory_module_exists():
    assert importlib.util.find_spec("anlan.memory") is not None


@pytest.fixture
def memory():
    from anlan.memory import MemoryStore
    dsn = os.environ.get("ANLAN_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("ANLAN_TEST_DATABASE_URL required for real PG")
    clock = [NOW]
    store = MemoryStore(dsn, clock=lambda: clock[0])
    run(store.initialize())
    return store, Identity(tenant_id="memory-test-" + uuid4().hex, user_id="owner"), clock


async def candidate(store, who, **changes):
    source = await store.feedback(who, {**FEEDBACK, **changes})
    return await store.propose(who, source["source_ref"], source["version"])


@pytest.mark.postgres
def test_confirm_reject_correct_conflict_and_history(memory):
    from anlan.memory import MemoryConflict
    store, who, _ = memory

    async def scenario():
        m = await candidate(store, who)
        assert m["status"] == "candidate" and m["revision"] == 1
        assert m["source_hash"] and await store.list_active(who) == []
        rejected = await store.change(who, m["memory_id"], 1, "reject")
        assert rejected["status"] == "rejected"
        await store.feedback(who, {**FEEDBACK, "version": 2, "value": "detailed"})
        corrected = await store.change(who, m["memory_id"], 2, "correct",
                                       source_ref="feedback-demo", source_version=2)
        assert corrected["status"] == "candidate" and corrected["value"] == "detailed"
        active = await store.change(who, m["memory_id"], 3, "confirm")
        assert (await store.list_active(who)) == [active]
        await store.change(who, m["memory_id"], 4, "conflict")
        assert await store.list_active(who) == []
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 5, "confirm")
        history = await store.history(who, m["memory_id"])
        assert [x["status"] for x in history] == [
            "candidate", "rejected", "candidate", "active", "conflicted"]
        assert history[0]["source_version"] == 1 and history[-1]["source_version"] == 2
    run(scenario())


@pytest.mark.postgres
def test_source_ownership_immutability_and_rejected_payload_do_not_write(memory):
    from anlan.memory import MemoryConflict
    from anlan.registry import AccessDenied
    store, who, _ = memory

    async def scenario():
        m = await candidate(store, who)
        for stranger in (Identity(tenant_id=who.tenant_id, user_id="other"),
                         Identity(tenant_id="other", user_id=who.user_id)):
            for action in (store.propose(stranger, "feedback-demo", 1),
                           store.get(stranger, m["memory_id"]),
                           store.history(stranger, m["memory_id"]),
                           store.change(stranger, m["memory_id"], 1, "confirm")):
                with pytest.raises(AccessDenied):
                    await action
            assert await store.list_active(stranger) == []
        with pytest.raises(MemoryConflict):
            await store.feedback(who, {**FEEDBACK, "value": "detailed"})
        with pytest.raises(AccessDenied):
            await store.propose(who, "invented", 1)
        for changes in ({"key": "area_safe"}, {"value": "approve"},
                        {"tenant_id": "other"}, {"data_origin": "REAL"},
                        {"observed_at": (NOW + timedelta(days=1)).isoformat()},
                        {"expires_at": NOW.isoformat()}):
            with pytest.raises(ValueError):
                await store.feedback(who, {**FEEDBACK, **changes})
        assert await store.get(who, m["memory_id"]) == m
        assert len(await store.history(who, m["memory_id"])) == 1
    run(scenario())


@pytest.mark.postgres
def test_old_revisions_source_replays_and_delete_never_resurrect(memory):
    from anlan.memory import MemoryConflict
    store, who, _ = memory

    async def scenario():
        m = await candidate(store, who)
        assert await store.propose(who, "feedback-demo", 1) == m
        await store.change(who, m["memory_id"], 1, "confirm")
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 1, "reject")
        await store.feedback(who, {**FEEDBACK, "version": 2, "value": "detailed"})
        with pytest.raises(MemoryConflict):
            await store.propose(who, "feedback-demo", 2)
        await store.change(who, m["memory_id"], 2, "correct",
                           source_ref="feedback-demo", source_version=2)
        with pytest.raises(MemoryConflict):
            await store.propose(who, "feedback-demo", 1)
        deleted = await store.change(who, m["memory_id"], 3, "delete")
        assert await store.propose(who, "feedback-demo", 2) == deleted
        for operation in ("confirm", "correct", "delete"):
            with pytest.raises(MemoryConflict):
                await store.change(who, m["memory_id"], 4, operation,
                                   source_ref="feedback-demo", source_version=1)
        assert await store.list_active(who) == []
        assert len(await store.history(who, m["memory_id"])) == 4
    run(scenario())


@pytest.mark.postgres
def test_expiry_filter_and_clock_boundaries(memory):
    from anlan.memory import MemoryConflict
    store, who, clock = memory

    async def scenario():
        m = await candidate(store, who)
        await store.change(who, m["memory_id"], 1, "confirm")
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 2, "expire")
        clock[0] = NOW - timedelta(seconds=1)
        assert await store.list_active(who) == []
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 2, "delete")
        clock[0] = NOW + timedelta(days=30)
        assert await store.list_active(who) == []
        expired = await store.change(who, m["memory_id"], 2, "expire")
        assert expired["status"] == "expired"
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 3, "confirm")
        assert (await store.get(who, m["memory_id"]))["revision"] == 3
    run(scenario())


@pytest.mark.postgres
def test_concurrent_confirm_has_exactly_one_winner(memory):
    from anlan.memory import MemoryConflict
    store, who, _ = memory

    async def scenario():
        m = await candidate(store, who)
        results = await asyncio.gather(*[
            store.change(who, m["memory_id"], 1, "confirm") for _ in range(5)
        ], return_exceptions=True)
        assert sum(isinstance(r, dict) for r in results) == 1
        assert sum(isinstance(r, MemoryConflict) for r in results) == 4
        assert len(await store.history(who, m["memory_id"])) == 2
    run(scenario())


@pytest.mark.postgres
def test_unconsumed_older_feedback_cannot_override_newer_source(memory):
    from anlan.memory import MemoryConflict
    store, who, _ = memory

    async def scenario():
        await store.feedback(who, FEEDBACK)
        m = await candidate(store, who, version=3, value="detailed")
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 1, "correct",
                               source_ref="feedback-demo", source_version=1)
        assert await store.get(who, m["memory_id"]) == m
    run(scenario())


@pytest.mark.postgres
def test_audit_failure_rolls_back_current_state(memory, monkeypatch):
    store, who, _ = memory
    original = store._save

    async def fail_after_write(conn, snapshot):
        await original(conn, snapshot)
        raise RuntimeError("injected failure after audit insert")

    async def scenario():
        m = await candidate(store, who)
        monkeypatch.setattr(store, "_save", fail_after_write)
        with pytest.raises(RuntimeError):
            await store.change(who, m["memory_id"], 1, "confirm")
        assert await store.get(who, m["memory_id"]) == m
        assert len(await store.history(who, m["memory_id"])) == 1
    run(scenario())


@pytest.mark.postgres
def test_intermediate_source_does_not_bypass_version_watermark(memory):
    from anlan.memory import MemoryConflict
    store, who, _ = memory

    async def scenario():
        await store.feedback(who, FEEDBACK)
        m = await candidate(store, who, version=3)
        await store.feedback(who, {**FEEDBACK, "source_ref": "another-source"})
        corrected = await store.change(who, m["memory_id"], 1, "correct",
                                       source_ref="another-source", source_version=1)
        with pytest.raises(MemoryConflict):
            await store.change(who, m["memory_id"], 2, "correct",
                               source_ref="feedback-demo", source_version=1)
        assert await store.get(who, m["memory_id"]) == corrected
    run(scenario())
