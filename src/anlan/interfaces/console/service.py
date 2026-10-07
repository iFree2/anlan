"""Scoped lists and server-bound synthetic events; no model or approval authority."""

from datetime import timedelta
from importlib.resources import files

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.perception import PerceptionStore
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.event_contracts import SourceBinding, digest
from anlan.workflows.material_analysis import OfflineAnalyzer


def source_id(identity, task_id, kind):
    return "console-" + digest([identity.model_dump(), task_id, kind])


class ConsoleService:
    def __init__(self, dsn, config, *, clock):
        self.dsn, self.config = dsn, config
        self.events = EventStore(dsn, clock=clock)

    def profile(self, identity):
        profile = self.config.console_profile(identity)
        if profile is None:
            raise AccessDenied("当前身份未配置合成事件模拟权限")
        return profile

    async def initialize(self):
        async with await self.events.connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421109)")
            await conn.execute(files("anlan").joinpath("sql/009_console_order.sql").read_text(
                encoding="utf-8"), prepare=False)

    async def tasks(self, identity):
        async with await self.events.connect() as conn:
            cursor = await conn.execute(
                "SELECT task_id,created_at,initial_state->'fields' AS initial_fields "
                "FROM anlan_v2.anlan_tasks WHERE tenant_id=%s AND user_id=%s AND mode='offline' "
                "ORDER BY created_at DESC,task_id DESC LIMIT 50",
                (identity.tenant_id, identity.user_id),
            )
            return {"items": await cursor.fetchall(), "limit": 50}

    async def list_events(self, identity, task_id):
        # Check ownership even when no event exists; empty result does not bypass authorization.
        async with postgres_service(self.dsn, OfflineAnalyzer()) as workflow:
            async with workflow._registry.locked(identity, task_id):
                cursor = await workflow._registry.conn.execute(
                    "SELECT document,result FROM anlan_v2.perception_events "
                    "WHERE tenant_id=%s AND user_id=%s AND document->'binding'->>'task_id'=%s "
                    "ORDER BY console_order DESC LIMIT 50",
                    (identity.tenant_id, identity.user_id, task_id),
                )
                return {"items": [self.events._document(r) for r in await cursor.fetchall()],
                        "limit": 50}

    async def reviews(self, identity, receipt):
        await self.events.get(identity, receipt)
        async with await self.events.connect() as conn:
            cursor = await conn.execute(
                "SELECT document,result,revision,feedback,cancel_requested "
                "FROM anlan_v2.perception_reviews "
                "WHERE tenant_id=%s AND user_id=%s AND receipt_id=%s "
                "ORDER BY console_order DESC LIMIT 20",
                (identity.tenant_id, identity.user_id, receipt),
            )
            return {"items": [PerceptionStore.document(r) for r in await cursor.fetchall()],
                    "limit": 20}

    async def simulate(self, identity, task_id, request):
        profile = self.profile(identity)
        sid = source_id(identity, task_id, request.kind)
        async with postgres_service(self.dsn, OfflineAnalyzer()) as workflow:
            registry = workflow._registry
            async with registry.locked(identity, task_id) as record:
                async with registry.conn.transaction():
                    await self.events._stream_lock(registry.conn, identity, sid)
                    cursor = await registry.conn.execute(
                        "SELECT document,result FROM anlan_v2.perception_events "
                        "WHERE tenant_id=%s AND user_id=%s AND source_id IN (%s,%s) "
                        "AND event_id=%s",
                        (identity.tenant_id, identity.user_id,
                         source_id(identity, task_id, "helmet_missing"),
                         source_id(identity, task_id, "gas_abnormal"), request.request_id),
                    )
                    previous = await cursor.fetchone()
                    if previous:
                        event = self.events._document(previous)
                        if (event["binding"]["revision"] != request.expected_revision
                                or event["raw"]["kind"] != request.kind):
                            raise InvalidTransition("同事件请求的材料版本或类型不同")
                        return event
                    workflow._check_mode(record)
                    state = (await workflow._snapshot(record)).values
                    if (not state or state["revision"] != request.expected_revision
                            or state["status"] not in {"waiting_input", "awaiting_review"}
                            or await registry.pending(task_id)):
                        raise InvalidTransition("请刷新材料状态后再生成合成事件")
                    now = self.events.now()
                    head = await self.events._head(registry.conn, identity, sid)
                    binding = SourceBinding(
                        identity=identity, source_id=sid, kind=request.kind,
                        object_ref=profile.references.area_id, task_id=task_id,
                        revision=state["revision"], run_id=state["run_id"],
                        valid_from=now - timedelta(seconds=1),
                        valid_until=now + timedelta(minutes=15),
                    )
                    payload = {
                        "schema_version": "perception-event-v1", "data_origin": "SYNTHETIC",
                        "event_id": request.request_id, "sequence": head["sequence"] + 1
                        if head else 1, "object_ref": binding.object_ref,
                        "observed_at": now.isoformat(),
                        "expires_at": (now + timedelta(minutes=10)).isoformat(),
                        "alarm_state": "active", "kind": request.kind,
                    }
                    payload.update({"confidence": 0.92} if request.kind == "helmet_missing"
                                   else {"value": 18.0, "unit": "percent_lel"})
                    return await self.events.receive(identity, sid, payload, binding,
                                                     conn=registry.conn)

    async def review(self, identity, receipt, request_id, runtime):
        profile = self.profile(identity)
        event = await self.events.get(identity, receipt)
        binding = event["binding"]
        if (not binding or event["source_id"] != source_id(
                identity, binding["task_id"], event["raw"]["kind"])
                or binding["object_ref"] != profile.references.area_id):
            raise AccessDenied("事件不属于当前合成操作台来源")
        return await runtime.review(identity, receipt, profile.references.model_dump(),
                                    request_id=request_id)
