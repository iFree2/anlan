"""Review reservations and feedback, independent of immutable raw alarms."""

from importlib.resources import files
from uuid import uuid4

from psycopg.types.json import Jsonb

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.infrastructure.events import EventStore


class PerceptionStore:
    def __init__(self, dsn, *, clock=None):
        self.events = EventStore(dsn, clock=clock)

    async def initialize(self):
        async with await self.events.connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421107)")
            await conn.execute(
                files("anlan")
                .joinpath("sql/007_perception_reviews.sql")
                .read_text(encoding="utf-8"),
                prepare=False,
            )
            await conn.execute(
                files("anlan")
                .joinpath("sql/008_perception_cancel.sql")
                .read_text(encoding="utf-8"),
                prepare=False,
            )

    @staticmethod
    def document(row):
        return row["document"] | {
            k: row[k] for k in ("result", "revision", "feedback", "cancel_requested")
        }

    async def get(self, identity, review_id, *, conn=None, lock=False):
        if conn is None:
            async with await self.events.connect() as conn:
                return await self.get(identity, review_id, conn=conn)
        cursor = await conn.execute(
            "SELECT document,result,revision,feedback,cancel_requested "
            "FROM anlan_v2.perception_reviews "
            "WHERE review_id=%s AND tenant_id=%s AND user_id=%s" + (" FOR UPDATE" if lock else ""),
            (review_id, identity.tenant_id, identity.user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied("重核记录不存在或当前身份无权访问")
        return self.document(row)

    async def previous(self, conn, identity, receipt_id, request_id, references):
        cursor = await conn.execute(
            "SELECT document,result,revision,feedback,cancel_requested "
            "FROM anlan_v2.perception_reviews "
            "WHERE tenant_id=%s AND user_id=%s AND receipt_id=%s AND request_id=%s",
            (identity.tenant_id, identity.user_id, receipt_id, request_id),
        )
        row = await cursor.fetchone()
        if row is not None:
            value = self.document(row)
            if value["references"] != references:
                raise InvalidTransition("相同重核request_id的引用不同")
            return value

    @staticmethod
    async def acquire(conn, review_id):
        cursor = await conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired",
            ("perception-review:" + review_id,),
        )
        if not (await cursor.fetchone())["acquired"]:
            raise TaskBusy("感知重核仍由其他执行者运行")

    @staticmethod
    async def release(conn, review_id):
        if not conn.closed:
            await conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                ("perception-review:" + review_id,),
            )

    async def reserve(self, conn, identity, event, request_id, references):
        review_id = str(uuid4())
        await self.acquire(conn, review_id)
        binding = event["binding"]
        value = {
            "data_origin": "SYNTHETIC",
            "review_id": review_id,
            "run_id": review_id,
            "receipt_id": event["receipt_id"],
            "request_id": request_id,
            "task_id": binding["task_id"],
            "material_revision": binding["revision"],
            "material_run_id": binding["run_id"],
            "references": references,
            "created_at": self.events.now().isoformat(),
        }
        await conn.execute(
            "INSERT INTO anlan_v2.perception_reviews "
            "(review_id,tenant_id,user_id,receipt_id,request_id,document) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                review_id,
                identity.tenant_id,
                identity.user_id,
                event["receipt_id"],
                request_id,
                Jsonb(value),
            ),
        )
        return value | {"result": None, "revision": 1, "feedback": None, "cancel_requested": False}

    async def finish(self, conn, identity, review_id, report, currentness, *, cancel_event=None):
        async with conn.transaction():
            row = await self.get(identity, review_id, conn=conn, lock=True)
            if row["result"] is not None:
                return row
            if row["cancel_requested"] or (cancel_event is not None and cancel_event.is_set()):
                report = {
                    **report,
                    "stop_reason": "cancelled",
                    "candidate": None,
                    "discarded_candidate": report.get("candidate"),
                }
            stop = report["stop_reason"]
            status = (
                "completed"
                if stop == "completed"
                else stop
                if stop in {"cancelled", "interrupted"}
                else "failed"
            )
            if status == "completed" and currentness != "current":
                status = "stale"
            result = {
                "status": status,
                "report": report,
                "currentness_at_finish": currentness,
                "completed_at": self.events.now().isoformat(),
            }
            await conn.execute(
                "UPDATE anlan_v2.perception_reviews SET result=%s WHERE review_id=%s",
                (Jsonb(result), review_id),
            )
            return row | {"result": result}

    async def feedback(self, conn, identity, review_id, payload, currentness):
        async with conn.transaction():
            row = await self.get(identity, review_id, conn=conn, lock=True)
            cursor = await conn.execute(
                "SELECT payload FROM anlan_v2.perception_feedback "
                "WHERE review_id=%s AND request_id=%s",
                (review_id, payload["request_id"]),
            )
            previous = await cursor.fetchone()
            if previous:
                if previous["payload"] != payload:
                    raise InvalidTransition("相同反馈request_id的内容不同")
                return row
            if (
                currentness != "current"
                or row["result"] is None
                or row["result"]["status"] != "completed"
                or row["revision"] != payload["expected_revision"]
            ):
                raise InvalidTransition("重核已过时、未完成或反馈版本冲突")
            feedback = {**payload, "recorded_at": self.events.now().isoformat()}
            await conn.execute(
                "INSERT INTO anlan_v2.perception_feedback (review_id,request_id,payload) "
                "VALUES (%s,%s,%s)",
                (review_id, payload["request_id"], Jsonb(payload)),
            )
            await conn.execute(
                "UPDATE anlan_v2.perception_reviews SET revision=revision+1,feedback=%s "
                "WHERE review_id=%s",
                (Jsonb(feedback), review_id),
            )
            return row | {"revision": row["revision"] + 1, "feedback": feedback}

    async def request_cancel(self, identity, review_id):
        async with await self.events.connect() as conn:
            row = await self.get(identity, review_id, conn=conn, lock=True)
            if row["result"] is None:
                await conn.execute(
                    "UPDATE anlan_v2.perception_reviews SET cancel_requested=true "
                    "WHERE review_id=%s",
                    (review_id,),
                )
