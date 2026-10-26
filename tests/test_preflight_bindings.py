"""B1 binding permissions, versions and transactions on real PG checkpoints."""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import COMPLETE, PATCH
from test_preflight_catalog import metadata, write_access
from test_preflight_contracts import command

from anlan.collaboration.service import CollaborationService
from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.interfaces.runtime import postgres_service
from anlan.interfaces.service_config import ServiceConfig
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres


@asynccontextmanager
async def setup(dsn, directory, fields=COMPLETE):  # noqa: F811
    tenant = "precheck-" + uuid4().hex
    actors = [Identity(tenant_id=tenant, user_id=user) for user in
              ("applicant", "reviewer", "stranger", "unassigned", "legacy")]
    actors += [Identity(tenant_id=tenant + "-foreign", user_id="applicant")]
    roles = ["applicant", "safety_manager", "applicant", "safety_manager", None, "applicant"]
    config = ServiceConfig.model_validate(dict(
        schema_version="local-service-v1", facts_dir=directory,
        tokens=[dict(token=str(i) * 64, identity=actor, collaboration_role=role)
                for i, (actor, role) in enumerate(zip(actors, roles), 1)],
        precheck_catalogs=[metadata(tenant)]))
    write_access(directory, actors[0])
    await CollaborationStore(dsn).initialize()

    def factory():
        return postgres_service(dsn, OfflineAnalyzer(), access_config=config)

    async with factory() as workflow:
        state = await workflow.start(actors[0], fields)
    # RED exercises real task/checkpoint creation before the missing new capability.
    from anlan.infrastructure.preflight import PrecheckStore
    from anlan.preflight.bindings import BindingService

    store = PrecheckStore(dsn)
    await store.initialize()
    yield BindingService(dsn, config, factory), actors, state, CollaborationService(
        dsn, config, factory)


async def send(collab, actor, task, action, version=1, revision=1, **extra):
    return await collab.execute(actor, task, action, dict(
        request_id=uuid4().hex, expected_application_version=version,
        expected_material_revision=revision, **extra))


async def counts(service, actor):
    async with service.store.connection() as conn:
        result = []
        for table in ("binding_heads", "binding_versions", "binding_commands"):
            cursor = await conn.execute(
                f"SELECT count(*) AS n FROM anlan_v2.precheck_{table} WHERE tenant_id=%s",
                (actor.tenant_id,))
            result.append((await cursor.fetchone())["n"])
        return result


def test_confirm_get_reconnect_and_noop_revision(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            task, owner = state["task_id"], actors[0]
            assert await service.get(owner, task) is None
            assert len((await service.catalog(owner, task)).workers) == 2
            first = await service.confirm(owner, task, command())
            assert first.binding_revision == 1
            assert first.material_revision_at_confirmation == 1
            assert first.confirmed_by == owner and first.confirmed_at.utcoffset() is not None
            assert await service.get(owner, task) == first
            assert await service.confirm(owner, task, command()) == first
            noop = command(request_id="noop", expected_binding_revision=1)
            assert await service.confirm(owner, task, noop) == first
            from anlan.preflight.bindings import BindingService

            fresh = BindingService(dsn, service.config, service.service_context_factory)
            assert await fresh.get(owner, task) == first
            assert await counts(service, owner) == [1, 1, 2]
            async with service.service_context_factory() as workflow:
                assert await workflow.get(owner, task) == state
    run(scenario())


@pytest.mark.parametrize("mutation", [
    {"worker_id": "worker-b"}, {"expected_material_revision": 2},
    {"expected_binding_revision": 1}, {"request_id": "bind-1 "},
])
def test_idempotency_compares_full_payload(dsn, tmp_path, mutation):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            first = await service.confirm(actors[0], state["task_id"], command())
            # A whitespace-distinct request is new, so its stale expected revision conflicts.
            with pytest.raises(InvalidTransition):
                await service.confirm(actors[0], state["task_id"], command(**mutation))
            assert await counts(service, actors[0]) == [1, 1, 1]
            assert await service.get(actors[0], state["task_id"]) == first
    run(scenario())


def test_material_and_binding_revisions_are_independent(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            task, owner = state["task_id"], actors[0]
            await service.confirm(owner, task, command())
            second = await service.confirm(owner, task, command(
                request_id="second", expected_binding_revision=1,
                worker_id="worker-b", area_id="area-b"))
            assert second.binding_revision == 2
            assert second.material_revision_at_confirmation == 1
            async with service.service_context_factory() as workflow:
                revised = await workflow.revise(owner, task, 1, PATCH)
            for body in (command(request_id="old-binding", expected_binding_revision=1,
                                 expected_material_revision=2),
                         command(request_id="old-material", expected_binding_revision=2)):
                with pytest.raises(InvalidTransition):
                    await service.confirm(owner, task, body)
            third = await service.confirm(owner, task, command(
                request_id="third", expected_binding_revision=2, expected_material_revision=2))
            assert third.binding_revision == 3 and third.material_revision_at_confirmation == 2
            async with service.service_context_factory() as workflow:
                assert await workflow.get(owner, task) == revised
    run(scenario())


def test_roles_tenants_participants_and_revocation(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, collab):
            task, owner, reviewer = state["task_id"], actors[0], actors[1]
            first = await service.confirm(owner, task, command())
            for actor in actors[1:]:
                for method, args in ((service.catalog, ()), (service.get, ()),
                                     (service.confirm, (command(),))):
                    with pytest.raises(AccessDenied):
                        await method(actor, task, *args)
            await send(collab, owner, task, "submit", reviewer_user_id=reviewer.user_id)
            # Assigned reviewer still needs their own facts access.
            with pytest.raises(AccessDenied):
                await service.get(reviewer, task)
            write_access(tmp_path, reviewer)
            assert await service.get(reviewer, task) == first
            with pytest.raises(AccessDenied):
                await service.confirm(reviewer, task, command())
            await send(collab, reviewer, task, "request_changes", 2, questions=["请确认对象"])
            write_access(tmp_path, owner, workers=(), areas=())
            with pytest.raises(AccessDenied):
                await service.get(owner, task)
            with pytest.raises(AccessDenied):
                await service.confirm(owner, task, command())
            write_access(tmp_path, owner)
            service.config.tokens = [g for g in service.config.tokens if g.identity != owner]
            for method, args in ((service.catalog, ()), (service.get, ()),
                                 (service.confirm, (command(),))):
                with pytest.raises(AccessDenied):
                    await method(owner, task, *args)
    run(scenario())


def test_stages_freeze_replays_but_changes_requested_allows_binding(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, collab):
            task, owner, reviewer = state["task_id"], actors[0], actors[1]
            await service.confirm(owner, task, command())
            await send(collab, owner, task, "submit", reviewer_user_id=reviewer.user_id)
            for body in (command(), command(request_id="frozen", expected_binding_revision=1)):
                with pytest.raises(InvalidTransition):
                    await service.confirm(owner, task, body)
            await send(collab, reviewer, task, "request_changes", 2, questions=["请换区域"])
            result = await service.confirm(owner, task, command(
                request_id="changed", expected_binding_revision=1, area_id="area-b"))
            assert result.binding_revision == 2
            async with service.service_context_factory() as workflow:
                await workflow.revise(owner, task, 1, PATCH)
            await send(collab, owner, task, "resubmit", 3, 2, reply="已修改")
            await send(collab, reviewer, task, "complete_review", 4, 2, conclusion="人工核对")
            with pytest.raises(InvalidTransition):
                await service.confirm(owner, task, command(
                    request_id="completed", expected_material_revision=2,
                    expected_binding_revision=2))
    run(scenario())


def test_directory_rejection_and_client_authority_injection(dsn, tmp_path):  # noqa: F811
    async def scenario():
        from pydantic import ValidationError

        async with setup(dsn, tmp_path) as (service, actors, state, _):
            for changes in ({"worker_id": "worker-hidden"}, {"area_id": "area-hidden"},
                            {"qualification_type": "electrical"}):
                with pytest.raises(AccessDenied):
                    await service.confirm(actors[0], state["task_id"], command(**changes))
            for changes in ({"actor": actors[1].model_dump()}, {"role": "safety_manager"},
                            {"confirmed_by": actors[0].model_dump()}, {"ready": True}):
                with pytest.raises(ValidationError):
                    await service.confirm(actors[0], state["task_id"], command(**changes))
            assert await counts(service, actors[0]) == [0, 0, 0]
    run(scenario())


@pytest.mark.parametrize("change", ["pending", "missing", "contract", "mode"])
def test_confirm_checks_real_checkpoint_and_pending_before_replay(
        dsn, tmp_path, change):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            task = state["task_id"]
            await service.confirm(actors[0], task, command())
            async with service.store.connection() as conn:
                if change == "pending":
                    await conn.execute("UPDATE anlan_v2.anlan_operations SET result=NULL "
                                       "WHERE task_id=%s", (task,))
                elif change == "missing":
                    await conn.execute("DELETE FROM anlan_v2.checkpoints WHERE thread_id=%s",
                                       (state["thread_id"],))
                else:
                    column = "contract_version" if change == "contract" else "mode"
                    await conn.execute(f"UPDATE anlan_v2.anlan_tasks SET {column}='invalid' "
                                       "WHERE task_id=%s", (task,))
            with pytest.raises(InvalidTransition):
                await service.confirm(actors[0], task, command())
            assert await counts(service, actors[0]) == [1, 1, 1]
    run(scenario())


def test_waiting_input_cannot_confirm(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path, fields={}) as (service, actors, state, _):
            with pytest.raises(InvalidTransition):
                await service.confirm(actors[0], state["task_id"], command())
    run(scenario())


def test_transaction_rolls_back_version_head_and_receipt(dsn, tmp_path, monkeypatch):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            async def broken(*args, **kwargs):
                raise RuntimeError("controlled receipt failure")

            with monkeypatch.context() as context:
                context.setattr(service.store, "save_receipt", broken)
                with pytest.raises(RuntimeError, match="receipt failure"):
                    await service.confirm(actors[0], state["task_id"], command())
            assert await counts(service, actors[0]) == [0, 0, 0]
            result = await service.confirm(actors[0], state["task_id"], command())
            assert result.binding_revision == 1
    run(scenario())


def test_real_task_lock_serializes_binding_and_materials(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            task, owner = state["task_id"], actors[0]
            async with service.service_context_factory() as workflow:
                async with workflow._registry.locked(owner, task):
                    with pytest.raises(TaskBusy):
                        await service.confirm(owner, task, command())
            bodies = [command(request_id=f"race-{i}", worker_id=f"worker-{letter}")
                      for i, letter in enumerate(("a", "b"))]
            results = await asyncio.gather(*[service.confirm(owner, task, body)
                                            for body in bodies], return_exceptions=True)
            assert sum(not isinstance(r, Exception) for r in results) == 1
            assert all(not isinstance(r, Exception) or isinstance(r, (TaskBusy, InvalidTransition))
                       for r in results)
            assert await counts(service, owner) == [1, 1, 1]
    run(scenario())


def test_cross_task_request_race_is_atomic_and_separate_from_collaboration(
        dsn, tmp_path, monkeypatch):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, collab):
            owner = actors[0]
            async with service.service_context_factory() as workflow:
                other = await workflow.start(owner, COMPLETE)
            entered, release = asyncio.Event(), asyncio.Event()
            original = service.store.save_receipt

            async def pause(*args, **kwargs):
                entered.set()
                await release.wait()
                return await original(*args, **kwargs)

            with monkeypatch.context() as context:
                context.setattr(service.store, "save_receipt", pause)
                first = asyncio.create_task(service.confirm(owner, state["task_id"], command()))
                try:
                    async with asyncio.timeout(10):
                        await entered.wait()
                    second = asyncio.create_task(service.confirm(
                        owner, other["task_id"], command()))
                    # First writer holds the real namespace lock; wait for the second backend
                    # to request an advisory lock before releasing the first transaction.
                    async with asyncio.timeout(10), service.store.connection() as conn:
                        while not second.done():
                            row = await (await conn.execute(
                                "SELECT 1 FROM pg_locks WHERE database=(SELECT oid "
                                "FROM pg_database WHERE datname=current_database()) "
                                "AND locktype='advisory' AND NOT granted")).fetchone()
                            if row:
                                break
                        assert not second.done()
                finally:
                    release.set()
                    results = await asyncio.gather(first, second, return_exceptions=True)
            assert not isinstance(results[0], Exception)
            assert isinstance(results[1], InvalidTransition)
            assert await counts(service, owner) == [1, 1, 1]
            # P12 uses its own request namespace: the same text remains valid there.
            await collab.execute(owner, state["task_id"], "submit", dict(
                request_id="bind-1", expected_material_revision=1,
                expected_application_version=1, reviewer_user_id=actors[1].user_id))
    run(scenario())
