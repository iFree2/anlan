"""Durable jobs with PG-clock leases, fenced attempts and append-only results."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from anlan.common.errors import InvalidTransition


class PrecheckJobs:
    async def defer(self, job_id, attempt_id, *, conn=None):
        """Relinquish this attempt's lease after task contention; a new claim audits expiry."""
        async with self.connection(conn) as database:
            await database.execute(
                "UPDATE anlan_v2.precheck_jobs j SET lease_until=clock_timestamp() "
                "WHERE job_id=%s AND status='running' AND EXISTS ("
                "SELECT 1 FROM anlan_v2.precheck_attempts a WHERE a.job_id=j.job_id "
                "AND a.attempt_id=%s AND a.status='running')",
                (job_id, attempt_id),
            )

    async def enqueue(self, actor, key, snapshot, *, cause="automatic", conn=None):
        async with self.connection(conn) as database:
            async with database.transaction():
                await database.execute(
                    "INSERT INTO anlan_v2.precheck_jobs "
                    "(job_id,tenant_id,task_id,material_revision,binding_revision,"
                    "application_version,actor_user_id,cause,input_snapshot) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        uuid4().hex,
                        actor.tenant_id,
                        key.task_id,
                        key.material_revision,
                        key.binding_revision,
                        key.application_version,
                        actor.user_id,
                        cause,
                        Jsonb(snapshot),
                    ),
                )
                row = await (
                    await database.execute(
                        "SELECT * FROM anlan_v2.precheck_jobs WHERE tenant_id=%s AND task_id=%s "
                        "AND material_revision=%s AND binding_revision=%s "
                        "AND application_version=%s AND cause=%s",
                        (
                            actor.tenant_id,
                            key.task_id,
                            key.material_revision,
                            key.binding_revision,
                            key.application_version,
                            cause,
                        ),
                    )
                ).fetchone()
                if row["actor_user_id"] != actor.user_id or row["input_snapshot"] != snapshot:
                    raise InvalidTransition("同一预核查输入键的发起人或快照冲突")
                return row

    async def claim(self, job_id=None):
        async with self.connection() as conn:
            async with conn.transaction():
                row = await (
                    await conn.execute(
                        "SELECT * FROM anlan_v2.precheck_jobs WHERE (status='queued' OR "
                        "(status='running' AND lease_until<=clock_timestamp())) "
                        "AND (%s::text IS NULL OR job_id=%s) ORDER BY ordinal "
                        "LIMIT 1 FOR UPDATE SKIP LOCKED",
                        (job_id, job_id),
                    )
                ).fetchone()
                if row is None:
                    return None
                await conn.execute(
                    "UPDATE anlan_v2.precheck_attempts SET status='expired',"
                    "finished_at=clock_timestamp() WHERE job_id=%s AND status='running'",
                    (row["job_id"],),
                )
                await conn.execute(
                    "UPDATE anlan_v2.precheck_jobs SET status='running',"
                    "lease_until=clock_timestamp()+interval '30 seconds',"
                    "updated_at=clock_timestamp() WHERE job_id=%s",
                    (row["job_id"],),
                )
                attempt_id = uuid4().hex
                await conn.execute(
                    "INSERT INTO anlan_v2.precheck_attempts "
                    "(attempt_id,job_id,status) VALUES (%s,%s,'running')",
                    (attempt_id, row["job_id"]),
                )
                return {"attempt_id": attempt_id, "job": row}

    async def finish(self, job_id, attempt_id, result, *, conn=None):
        # The service additionally holds the registry task lock and compares input.
        async with self.connection(conn) as database:
            async with database.transaction():
                job = await (
                    await database.execute(
                        "SELECT *,lease_until>clock_timestamp() AS leased "
                        "FROM anlan_v2.precheck_jobs WHERE job_id=%s FOR UPDATE",
                        (job_id,),
                    )
                ).fetchone()
                previous = await (
                    await database.execute(
                        "SELECT * FROM anlan_v2.precheck_results WHERE job_id=%s", (job_id,)
                    )
                ).fetchone()
                if previous and previous["attempt_id"] == attempt_id:
                    return previous
                if previous or not job or not job["leased"] or job["status"] != "running":
                    raise InvalidTransition("预核查租约或尝试已失效")
                attempt = await (
                    await database.execute(
                        "UPDATE anlan_v2.precheck_attempts SET status='completed',"
                        "finished_at=clock_timestamp() WHERE job_id=%s AND attempt_id=%s "
                        "AND status='running' RETURNING attempt_id",
                        (job_id, attempt_id),
                    )
                ).fetchone()
                if attempt is None:
                    raise InvalidTransition("迟到的预核查尝试不能发布结果")
                row = await (
                    await database.execute(
                        "INSERT INTO anlan_v2.precheck_results "
                        "(check_id,job_id,attempt_id,result) VALUES (%s,%s,%s,%s) RETURNING *",
                        (uuid4().hex, job_id, attempt_id, Jsonb(result)),
                    )
                ).fetchone()
                await database.execute(
                    "UPDATE anlan_v2.precheck_jobs SET status='completed',"
                    "lease_until=NULL,updated_at=clock_timestamp() WHERE job_id=%s",
                    (job_id,),
                )
                return row

    async def latest(self, tenant_id, task_id, *, conn=None):
        async with self.connection(conn) as database:
            return await (
                await database.execute(
                    "SELECT j.*,r.check_id,r.attempt_id,r.result FROM anlan_v2.precheck_jobs j "
                    "LEFT JOIN anlan_v2.precheck_results r USING(job_id) "
                    "WHERE j.tenant_id=%s AND j.task_id=%s ORDER BY j.ordinal DESC LIMIT 1",
                    (tenant_id, task_id),
                )
            ).fetchone()

    async def current_result(self, tenant_id, key, *, conn=None):
        row = await self.latest(tenant_id, key.task_id, conn=conn)
        if (
            row
            and row["result"] is not None
            and all(
                row[name] == getattr(key, name)
                for name in ("material_revision", "binding_revision", "application_version")
            )
        ):
            return row
        return None
