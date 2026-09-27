"""Scoped review lifecycle with the existing task lock, collector and PG budget gateway."""

import asyncio
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, TypeAdapter

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import StrictModel
from anlan.infrastructure.budget import AUTHORIZATION_ID
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.perception import PerceptionStore
from anlan.interfaces.event_runtime import process_event
from anlan.interfaces.runtime import postgres_service
from anlan.tools.contracts import FactReferences
from anlan.workflows.event_contracts import Identifier, SourceBinding, parse_event
from anlan.workflows.events import admission, material_status
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.parallel import collect_parallel
from anlan.workflows.perception import synthesize_perception


class Feedback(StrictModel):
    expected_revision: int = Field(strict=True, ge=1)
    request_id: Identifier
    decision: Literal["confirmed_event", "disputed_event", "needs_verification"]


class PerceptionRuntime:
    def __init__(self, dsn, tools=None, knowledge=None, memory=None, model=None, *, clock=None):
        self.dsn, self.tools, self.knowledge, self.memory, self.model = (
            dsn,
            tools,
            knowledge,
            memory,
            model,
        )
        self.clock = clock or (lambda: datetime.now(UTC))
        self.events = EventStore(dsn, clock=lambda: self.clock())
        self.store = PerceptionStore(dsn, clock=lambda: self.clock())

    async def _current(self, service, identity, event, record):
        conn = service._registry.conn
        await self.events._stream_lock(conn, identity, event["source_id"])
        source = SourceBinding.model_validate(event["binding"])
        try:
            state = (await service._snapshot(record)).values
        except InvalidTransition:
            return "material_contract_mismatch"
        if await service._registry.pending(source.task_id):
            return "material_pending"
        status = material_status(source, state)
        if status != "linked":
            return status
        temporal = admission(parse_event(event["raw"]), source, self.events.now())
        if temporal != "pending":
            return temporal
        head = await self.events._head(conn, identity, event["source_id"])
        if not head or head["receipt_id"] != event["receipt_id"]:
            return "superseded_event"
        return "current"

    async def get(self, identity, review_id):
        row = await self.store.get(identity, review_id)
        event = await self.events.get(identity, row["receipt_id"])
        async with postgres_service(self.dsn, OfflineAnalyzer()) as service:
            try:
                async with service._registry.locked(identity, row["task_id"]) as record:
                    async with service._registry.conn.transaction():
                        current = await self._current(service, identity, event, record)
            except (AccessDenied, TaskBusy):
                current = "task_unavailable"
        return row | {"currentness": current}

    async def _finish(self, service, identity, row, event, report, *, cancel_event=None):
        registry = service._registry
        try:
            async with registry.locked(identity, row["task_id"]) as record:
                async with registry.conn.transaction():
                    current = await self._current(service, identity, event, record)
                    value = await self.store.finish(
                        registry.conn,
                        identity,
                        row["review_id"],
                        report,
                        current,
                        cancel_event=cancel_event,
                    )
        except (TaskBusy, AccessDenied):
            current = "task_unavailable"
            value = await self.store.finish(
                registry.conn,
                identity,
                row["review_id"],
                report,
                current,
                cancel_event=cancel_event,
            )
        return value | {"currentness": current}

    async def review(self, identity, receipt_id, references, *, request_id, cancel_event=None):
        event = await self.events.get(identity, receipt_id)
        request_id = TypeAdapter(Identifier).validate_python(request_id)
        refs = FactReferences.model_validate(references).model_dump()
        source = SourceBinding.model_validate(event["binding"])
        if refs["area_id"] != source.object_ref:
            raise InvalidTransition("事实对象与可信事件绑定不同")
        if event["result"] is None:
            event = await process_event(self.dsn, identity, receipt_id, clock=self.clock)
        if event["result"]["status"] != "linked":
            raise InvalidTransition("只有已关联事件能进入重核")
        async with postgres_service(self.dsn, OfflineAnalyzer()) as service:
            registry = service._registry
            async with registry.locked(identity, source.task_id) as record:
                async with registry.conn.transaction():
                    current = await self._current(service, identity, event, record)
                    previous = await self.store.previous(
                        registry.conn, identity, receipt_id, request_id, refs
                    )
                    if previous:
                        return previous | {"currentness": current}
                    if current != "current":
                        raise InvalidTransition("事件或材料已过时，需要新的可信绑定与事件")
                    row = await self.store.reserve(registry.conn, identity, event, request_id, refs)
            report = {
                "stop_reason": "not_started",
                "event": event["raw"],
                "observations": [],
                "attempt_id": None,
                "requests_this_run": 0,
            }
            progress = {}
            signal = cancel_event if cancel_event is not None else asyncio.Event()
            monitor = asyncio.create_task(self._watch_cancel(identity, row["review_id"], signal))
            try:
                try:
                    question = (
                        "SYNTHETIC：未戴安全帽事件需核对哪些示例依据？"
                        if event["raw"]["kind"] == "helmet_missing"
                        else "SYNTHETIC：可燃气体浓度异常事件需核对哪些示例依据？"
                    )
                    collection = asyncio.create_task(
                        collect_parallel(
                            service,
                            identity,
                            source.task_id,
                            refs,
                            question,
                            self.tools,
                            self.knowledge,
                            self.memory,
                            cancel_event=signal,
                            progress=progress,
                        )
                    )
                    try:
                        bundle = await asyncio.shield(collection)
                    except asyncio.CancelledError as cancelled:
                        # Ask the bounded collector to fan in its completed observations first.
                        signal.set()
                        try:
                            bundle = await asyncio.shield(collection)
                            report["collection"] = bundle["collection"]
                        except Exception as exc:
                            report["collection_warning"] = type(exc).__name__
                        finally:
                            report["observations"] = progress.get("observations", [])
                            report["rejected_observations"] = progress.get(
                                "rejected_observations", []
                            )
                            if not collection.done():
                                collection.cancel()
                                await asyncio.gather(collection, return_exceptions=True)
                        raise cancelled
                    report["observations"] = bundle["observations"]
                    report = await synthesize_perception(
                        event["raw"], bundle, self.model, row["run_id"], cancel_event=signal
                    )
                except asyncio.CancelledError:
                    report["stop_reason"] = "cancelled"
                    gateway = getattr(self.model, "gateway", None)
                    if gateway:
                        report["attempt_id"] = self.model.attempt_for(row["run_id"])
                        report["requests_this_run"] = int(report["attempt_id"] is not None)
                    await self._finish(service, identity, row, event, report)
                    raise
                except Exception:
                    report["stop_reason"] = "collection_unavailable"
                    report["observations"] = progress.get("observations", report["observations"])
                return await self._finish(
                    service, identity, row, event, report, cancel_event=signal
                )
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
                await self.store.release(registry.conn, row["review_id"])

    async def _watch_cancel(self, identity, review_id, signal):
        try:
            while not signal.is_set():
                if (await self.store.get(identity, review_id))["cancel_requested"]:
                    signal.set()
                    return
                await asyncio.sleep(0.25)
        except Exception:
            signal.set()

    async def cancel(self, identity, review_id):
        await self.store.request_cancel(identity, review_id)
        return await self.get(identity, review_id)

    async def feedback(self, identity, review_id, expected_revision, decision, *, request_id):
        row = await self.store.get(identity, review_id)
        payload = Feedback(
            expected_revision=expected_revision, request_id=request_id, decision=decision
        ).model_dump()
        event = await self.events.get(identity, row["receipt_id"])
        async with postgres_service(self.dsn, OfflineAnalyzer()) as service:
            async with service._registry.locked(identity, row["task_id"]) as record:
                async with service._registry.conn.transaction():
                    current = await self._current(service, identity, event, record)
                    result = await self.store.feedback(
                        service._registry.conn, identity, review_id, payload, current
                    )
        return result | {"currentness": current}

    async def recover(self, identity, review_id):
        row = await self.store.get(identity, review_id)
        async with await self.events.connect() as conn:
            await self.store.acquire(conn, review_id)
            try:
                cursor = await conn.execute(
                    "SELECT attempt_id,status,usage FROM anlan_v2.model_budget_attempts "
                    "WHERE authorization_id=%s AND run_id=%s",
                    (AUTHORIZATION_ID, row["run_id"]),
                )
                attempts = await cursor.fetchall()
                report = {
                    "stop_reason": "interrupted",
                    "model_resubmitted": False,
                    "attempts": attempts,
                    "requests_this_run": len(attempts),
                }
                await self.store.finish(conn, identity, review_id, report, "not_revalidated")
            finally:
                await self.store.release(conn, review_id)
        return await self.get(identity, review_id)
