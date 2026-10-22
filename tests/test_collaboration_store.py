"""Collaboration registration and schema contracts against isolated real PostgreSQL."""

import asyncio
from importlib.resources import files
from uuid import uuid4

import pytest
from psycopg import AsyncConnection, errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_events_postgres import dsn, run  # noqa: F401 -- real PG, fail without explicit DSN

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.conversations import ConversationStore
from anlan.infrastructure.db import conninfo
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres


async def setup(dsn):  # noqa: F811 -- shared fixture
    owner = Identity(tenant_id="collab-" + uuid4().hex, user_id="applicant")
    reviewer = Identity(tenant_id=owner.tenant_id, user_id="reviewer")
    async with postgres_service(dsn, OfflineAnalyzer()) as service:
        state = await service.start(owner, DEMO_FIELDS)
    # Imported after task creation so RED also exercises the real database fixture.
    from anlan.infrastructure.collaboration import CollaborationStore

    store = CollaborationStore(dsn)
    await store.initialize()
    return store, owner, reviewer, state


async def task_row(dsn, task_id):  # noqa: F811 -- shared fixture
    async with await AsyncConnection.connect(conninfo(dsn), row_factory=dict_row) as conn:
        cursor = await conn.execute(
            "SELECT * FROM anlan_v2.anlan_tasks WHERE task_id=%s", (task_id,),
        )
        return await cursor.fetchone()


async def submitted(dsn, app, reviewer):  # noqa: F811 -- shared fixture
    """Seed future atomic-command rows directly; B1 exposes no command mutation API."""
    event_id = uuid4().hex
    async with await AsyncConnection.connect(conninfo(dsn)) as conn:
        await conn.execute(
            "UPDATE anlan_v2.collaboration_applications SET reviewer_user_id=%s,"
            "status='under_review',version=2,submitted_material_revision=1 WHERE task_id=%s",
            (reviewer.user_id, app.task_id),
        )
        await conn.execute(
            "INSERT INTO anlan_v2.collaboration_commands "
            "(tenant_id,actor_user_id,request_id,task_id,action,actor_role,"
            "expected_application_version,expected_material_revision,payload,result) "
            "VALUES (%s,%s,'submit-1',%s,'submit','applicant',1,1,%s,%s)",
            (app.tenant_id, app.applicant_user_id, app.task_id,
             Jsonb({"reviewer_user_id": reviewer.user_id}), Jsonb({"version": 2})),
        )
        await conn.execute(
            "INSERT INTO anlan_v2.collaboration_events "
            "(event_id,tenant_id,task_id,actor_user_id,actor_role,action,material_revision,"
            "application_version,payload) VALUES (%s,%s,%s,%s,'applicant','submit',1,2,%s)",
            (event_id, app.tenant_id, app.task_id, app.applicant_user_id,
             Jsonb({"reviewer_user_id": reviewer.user_id})),
        )
        await conn.execute(
            "INSERT INTO anlan_v2.collaboration_notifications "
            "(tenant_id,recipient_user_id,event_id) VALUES (%s,%s,%s)",
            (app.tenant_id, reviewer.user_id, event_id),
        )
    return event_id


def test_migration_resource_exists():
    assert files("anlan").joinpath("sql/017_collaboration.sql").is_file()


def test_ensure_draft_preserves_task_owner_and_is_idempotent(dsn):  # noqa: F811
    async def scenario():
        store, owner, _, state = await setup(dsn)
        before = await task_row(dsn, state["task_id"])
        apps = await asyncio.gather(*[
            store.ensure_draft(owner, "applicant", state["task_id"]) for _ in range(4)
        ])
        assert all(app == apps[0] for app in apps)
        app = apps[0]
        assert (app.task_id, app.tenant_id, app.applicant_user_id) == (
            state["task_id"], owner.tenant_id, owner.user_id,
        )
        assert app.status == "draft" and app.version == 1
        assert app.reviewer_user_id is app.submitted_material_revision is None
        assert app.completed_material_revision is None
        assert app.created_at is not None and app.updated_at is not None
        assert await store.get(owner, "applicant", app.task_id) == app
        assert await task_row(dsn, app.task_id) == before
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            assert await service.get(owner, app.task_id) == state
    run(scenario())


def test_assigned_visibility_and_cross_tenant_denial(dsn):  # noqa: F811
    async def scenario():
        store, owner, reviewer, state = await setup(dsn)
        app = await store.ensure_draft(owner, "applicant", state["task_id"])
        assert await store.list(reviewer, "safety_manager") == []
        with pytest.raises(AccessDenied):
            await store.get(reviewer, "safety_manager", app.task_id)
        await submitted(dsn, app, reviewer)
        shared = await store.get(reviewer, "safety_manager", app.task_id)
        assert shared.status == "under_review" and shared.version == 2
        assert await store.list(reviewer, "safety_manager") == [shared]
        assert await store.list(owner, "applicant") == [shared]
        assert await store.ensure_draft(owner, "applicant", app.task_id) == shared
        for stranger, role in [
            (Identity(tenant_id=owner.tenant_id, user_id="unassigned"), "safety_manager"),
            (Identity(tenant_id="foreign", user_id=reviewer.user_id), "safety_manager"),
            (Identity(tenant_id=owner.tenant_id, user_id="other"), "applicant"),
        ]:
            with pytest.raises(AccessDenied):
                await store.get(stranger, role, app.task_id)
            assert await store.list(stranger, role) == []
        for actor, role in [(owner, None), (owner, "safety_manager"), (reviewer, "applicant")]:
            with pytest.raises(AccessDenied):
                await store.get(actor, role, app.task_id)
        with pytest.raises(AccessDenied):
            await store.list(owner, None)
    run(scenario())


def test_registration_rejects_non_owner_unknown_task_and_legacy(dsn):  # noqa: F811
    async def scenario():
        store, owner, reviewer, state = await setup(dsn)
        for actor, role in [
            (reviewer, "safety_manager"), (reviewer, "applicant"), (owner, None),
            (Identity(tenant_id="foreign", user_id=owner.user_id), "applicant"),
        ]:
            with pytest.raises(AccessDenied):
                await store.ensure_draft(actor, role, state["task_id"])
        with pytest.raises(AccessDenied):
            await store.ensure_draft(owner, "applicant", "missing-" + uuid4().hex)
        assert await store.list(owner, "applicant") == []
        with pytest.raises(AccessDenied):
            await store.get(owner, "applicant", state["task_id"])
    run(scenario())


def test_reconnect_and_repeat_initialize_preserve_old_rows(dsn):  # noqa: F811
    async def scenario():
        store, owner, reviewer, state = await setup(dsn)
        before = await task_row(dsn, state["task_id"])
        conversations = ConversationStore(dsn)
        await conversations.initialize()
        private = await conversations.create(owner, "private")
        app = await store.ensure_draft(owner, "applicant", state["task_id"])
        event_id = await submitted(dsn, app, reviewer)
        app = await store.get(owner, "applicant", app.task_id)

        async def snapshot():
            async with await AsyncConnection.connect(conninfo(dsn), row_factory=dict_row) as conn:
                rows = []
                for table in ("commands", "events", "notifications"):
                    cursor = await conn.execute(
                        f"SELECT * FROM anlan_v2.collaboration_{table} WHERE tenant_id=%s",
                        (owner.tenant_id,),
                    )
                    rows.append(await cursor.fetchall())
                return rows

        durable = await snapshot()
        assert durable[1][0]["event_id"] == durable[2][0]["event_id"] == event_id
        fresh = type(store)(dsn)
        await fresh.initialize()
        await fresh.initialize()
        assert await fresh.get(reviewer, "safety_manager", app.task_id) == app
        assert await snapshot() == durable
        assert await task_row(dsn, app.task_id) == before
        assert await ConversationStore(dsn).get(owner, private["conversation_id"]) == private
        with pytest.raises(AccessDenied):
            await ConversationStore(dsn).get(reviewer, private["conversation_id"])
    run(scenario())


@pytest.mark.parametrize("mutation,error", [
    ("UPDATE anlan_v2.collaboration_applications SET version=0 WHERE task_id=%s",
     errors.CheckViolation),
    ("UPDATE anlan_v2.collaboration_applications SET reviewer_user_id=applicant_user_id "
     "WHERE task_id=%s", errors.CheckViolation),
    ("UPDATE anlan_v2.collaboration_applications SET status='review_completed' "
     "WHERE task_id=%s", errors.CheckViolation),
    ("UPDATE anlan_v2.collaboration_events SET actor_user_id=repeat('a',501) WHERE task_id=%s",
     errors.CheckViolation),
    ("UPDATE anlan_v2.collaboration_events SET actor_user_id='a'||repeat(' ',501) "
     "WHERE task_id=%s", errors.CheckViolation),
    ("UPDATE anlan_v2.collaboration_events SET application_version=0 WHERE task_id=%s",
     errors.CheckViolation),
    ("UPDATE anlan_v2.collaboration_commands SET action='approved' WHERE task_id=%s",
     errors.CheckViolation),
])
def test_schema_rejects_invalid_metadata(dsn, mutation, error):  # noqa: F811
    async def scenario():
        store, owner, reviewer, state = await setup(dsn)
        app = await store.ensure_draft(owner, "applicant", state["task_id"])
        await submitted(dsn, app, reviewer)
        async with await AsyncConnection.connect(conninfo(dsn)) as conn:
            with pytest.raises(error):
                async with conn.transaction(force_rollback=True):
                    await conn.execute(mutation, (app.task_id,))
    run(scenario())


def test_command_recipient_uniqueness_and_tenant_foreign_keys(dsn):  # noqa: F811
    async def scenario():
        store, owner, reviewer, state = await setup(dsn)
        app = await store.ensure_draft(owner, "applicant", state["task_id"])
        event_id = await submitted(dsn, app, reviewer)
        async with await AsyncConnection.connect(conninfo(dsn)) as conn:
            with pytest.raises(errors.UniqueViolation):
                async with conn.transaction(force_rollback=True):
                    await conn.execute(
                        "INSERT INTO anlan_v2.collaboration_notifications "
                        "(tenant_id,recipient_user_id,event_id) VALUES (%s,%s,%s)",
                        (owner.tenant_id, reviewer.user_id, event_id),
                    )
            with pytest.raises(errors.ForeignKeyViolation):
                async with conn.transaction(force_rollback=True):
                    await conn.execute(
                        "INSERT INTO anlan_v2.collaboration_notifications "
                        "(tenant_id,recipient_user_id,event_id) VALUES ('foreign',%s,%s)",
                        (reviewer.user_id, event_id),
                    )
            # Same actor/request cannot be reused even against a different task.
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                other = await service.start(owner, DEMO_FIELDS)
            await store.ensure_draft(owner, "applicant", other["task_id"])
            with pytest.raises(errors.UniqueViolation):
                async with conn.transaction(force_rollback=True):
                    await conn.execute(
                        "INSERT INTO anlan_v2.collaboration_commands "
                        "(tenant_id,actor_user_id,request_id,task_id,action,actor_role,"
                        "expected_application_version,expected_material_revision,payload,result) "
                        "VALUES (%s,%s,'submit-1',%s,'submit','applicant',1,1,'{}','{}')",
                        (owner.tenant_id, owner.user_id, other["task_id"]),
                    )
    run(scenario())
