"""Additive policy and binding SQL constraints, immutable history and legacy preservation."""

from importlib.resources import files

import pytest
from psycopg import errors
from test_events_postgres import dsn, run  # noqa: F401
from test_preflight_bindings import send, setup
from test_preflight_contracts import command

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.conversations import ConversationStore
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer

pytestmark = pytest.mark.postgres


def test_sql019_resource_exists():
    assert files("anlan").joinpath("sql/019_preflight_bindings.sql").is_file()


def test_migration_trigger_ddl_supports_postgres13():
    sql = files("anlan").joinpath("sql/019_preflight_bindings.sql").read_text(encoding="utf-8")
    # PG13 CREATE TRIGGER lacks the PG14 OR REPLACE grammar. The initializer's
    # advisory lock and transaction must protect the compatible drop/create pair.
    assert "CREATE OR REPLACE TRIGGER" not in sql.upper()


def test_policy_uses_actual_stage_and_preserves_later_policy(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, collab):
            owner, reviewer, task = actors[0], actors[1], state["task_id"]
            policy = await service.store.ensure_policy(owner.tenant_id, task)
            assert policy.required and not policy.legacy_completed
            await service.confirm(owner, task, command())
            await send(collab, owner, task, "submit", reviewer_user_id=reviewer.user_id)
            with pytest.raises(InvalidTransition):
                await send(collab, reviewer, task, "complete_review", 2, conclusion="旧人工核查")
            from test_preflight_service import populate_sources

            from anlan.preflight.runner import PreflightRunner
            from anlan.preflight.service import PreflightService
            from anlan.tools.queries import FactTools

            knowledge = await populate_sources(dsn, service.config, actors, tmp_path)
            preflight = PreflightService(dsn, service.config, service.service_context_factory,
                PreflightRunner(FactTools(tmp_path, clock=lambda: service.config.as_of), knowledge,
                                clock=lambda: service.config.as_of))
            job = await service.store.latest(owner.tenant_id, task)
            evidence = await preflight.process_next(job['job_id'])
            await send(collab, reviewer, task, 'complete_review', 2, conclusion='人工核对',
                expected_binding_revision=1, expected_check_id=evidence['check_id'],
                applied_knowledge_citation_ids=evidence['result']['citation_ids'])
            # A later completion must not reclassify a policy already created as required.
            assert await service.store.ensure_policy(owner.tenant_id, task) == policy
            async with service.service_context_factory() as workflow:
                other = await workflow.start(owner, state["fields"])
            # A controlled pre-P13 row has no policy yet and was already completed at upgrade.
            async with service.store.connection() as conn:
                await conn.execute('DELETE FROM anlan_v2.precheck_policies WHERE task_id=%s',
                                   (other['task_id'],))
                await conn.execute("UPDATE anlan_v2.collaboration_applications SET "
                    "status='review_completed',reviewer_user_id=%s,version=3,"
                    'submitted_material_revision=1,completed_material_revision=1 WHERE task_id=%s',
                    (reviewer.user_id, other['task_id']))
            historical = await collab.get(owner, other["task_id"])
            legacy = await service.store.ensure_policy(owner.tenant_id, other["task_id"])
            assert legacy.legacy_completed and not legacy.required
            await service.store.initialize()
            assert await service.store.ensure_policy(owner.tenant_id, task) == policy
            assert await service.store.ensure_policy(owner.tenant_id, other["task_id"]) == legacy
            assert await collab.get(owner, other["task_id"]) == historical
            with pytest.raises(AccessDenied):
                await service.store.ensure_policy("foreign", task)
    run(scenario())


def test_initialization_preserves_original_rows_and_does_not_activate_policy(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            conversations = ConversationStore(dsn)
            await conversations.initialize()
            private = await conversations.create(actors[0], "PRIVATE_SENTINEL")
            ledger = BudgetLedger(dsn, "precheck-history-" + actors[0].tenant_id, 1, 1)
            await ledger.initialize()
            async with await ledger._connect() as conn:
                await conn.execute("INSERT INTO anlan_v2.model_call_policies "
                    "(authorization_id,limits_enforced,reason) VALUES (%s,false,'SYNTHETIC audit')",
                    (ledger.authorization_id,))
            attempt = await ledger.reserve("P11-WP01", "SYNTHETIC-no-network")
            await ledger.finish(attempt, "failed", error="invalid_output")
            audit = await ledger.snapshot()
            assert audit["limits_enforced"] is False
            # A real pre-collaboration private task is never registered or shared by SQL019.
            async with postgres_service(dsn, OfflineAnalyzer()) as workflow:
                legacy = await workflow.start(actors[4], state["fields"])

            async def old_rows():
                result = {}
                async with service.store.connection() as conn:
                    for table in ("anlan_tasks", "anlan_operations", "collaboration_applications",
                                  "collaboration_events", "collaboration_commands"):
                        cursor = await conn.execute(f"SELECT * FROM anlan_v2.{table} "
                                                    "WHERE task_id=%s", (state["task_id"],))
                        result[table] = await cursor.fetchall()
                return result

            before = await old_rows()
            await service.store.initialize()
            await service.store.initialize()
            assert await old_rows() == before
            assert await conversations.get(actors[0], private["conversation_id"]) == private
            with pytest.raises(AccessDenied):
                await conversations.get(actors[1], private["conversation_id"])
            assert await ledger.snapshot() == audit
            with pytest.raises(AccessDenied):
                await service.store.ensure_policy(actors[4].tenant_id, legacy["task_id"])
            with pytest.raises(AccessDenied):
                await service.get(actors[4], legacy["task_id"])
            async with service.store.connection() as conn:
                row = await (await conn.execute("SELECT count(*) AS n FROM "
                    "anlan_v2.precheck_policies WHERE task_id=%s", (state["task_id"],))).fetchone()
                assert row["n"] == 1
            async with service.service_context_factory() as workflow:
                assert await workflow.get(actors[0], state["task_id"]) == state
            async with postgres_service(dsn, OfflineAnalyzer()) as workflow:
                assert await workflow.get(actors[4], legacy["task_id"]) == legacy
    run(scenario())


@pytest.mark.parametrize("mutation,error", [
    ("UPDATE anlan_v2.precheck_binding_versions SET worker_id='worker-b' WHERE task_id=%s",
     errors.RaiseException),
    ("DELETE FROM anlan_v2.precheck_binding_versions WHERE task_id=%s", errors.RaiseException),
    ("UPDATE anlan_v2.precheck_binding_commands SET request_id='altered' WHERE task_id=%s",
     errors.RaiseException),
    ("DELETE FROM anlan_v2.precheck_binding_commands WHERE task_id=%s", errors.RaiseException),
    ("UPDATE anlan_v2.precheck_binding_heads SET binding_revision=0 WHERE task_id=%s",
     errors.CheckViolation),
    ("UPDATE anlan_v2.precheck_binding_heads SET binding_revision=42 WHERE task_id=%s",
     errors.ForeignKeyViolation),
    ("UPDATE anlan_v2.precheck_binding_heads SET tenant_id='foreign' WHERE task_id=%s",
     errors.ForeignKeyViolation),
    ("UPDATE anlan_v2.precheck_policies SET required=false,legacy_completed=false WHERE task_id=%s",
     errors.CheckViolation),
])
def test_sql_constraints_and_immutable_history(dsn, tmp_path, mutation, error):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            await service.store.ensure_policy(actors[0].tenant_id, state["task_id"])
            await service.confirm(actors[0], state["task_id"], command())
            await service.store.initialize()
            await service.store.initialize()
            async with service.store.connection() as conn:
                with pytest.raises(error):
                    async with conn.transaction(force_rollback=True):
                        await conn.execute(mutation, (state["task_id"],))
    run(scenario())


def test_versions_and_actor_requests_are_unique_and_tenant_bound(dsn, tmp_path):  # noqa: F811
    async def scenario():
        async with setup(dsn, tmp_path) as (service, actors, state, _):
            task = state["task_id"]
            await service.confirm(actors[0], task, command())
            async with service.store.connection() as conn:
                for table in ("binding_versions", "binding_commands"):
                    with pytest.raises(errors.UniqueViolation):
                        async with conn.transaction(force_rollback=True):
                            await conn.execute(f"INSERT INTO anlan_v2.precheck_{table} "
                                f"SELECT * FROM anlan_v2.precheck_{table} WHERE task_id=%s",
                                (task,))
                with pytest.raises(errors.ForeignKeyViolation):
                    async with conn.transaction(force_rollback=True):
                        await conn.execute("UPDATE anlan_v2.precheck_policies "
                            "SET tenant_id='foreign' "
                            "WHERE task_id=%s",
                            (task,))
    run(scenario())
