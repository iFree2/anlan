"""Compose event association with the existing task lock and checkpoint connection."""
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.events import EventStore
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.event_contracts import SourceBinding
from anlan.workflows.events import material_status
from anlan.workflows.material_analysis import OfflineAnalyzer


async def process_event(dsn, identity, receipt_id, *, clock=None):
    store = EventStore(dsn, clock=clock)
    row = await store.get(identity, receipt_id)  # Event ownership before task/checkpoint access.
    if row["result"] is not None:
        return row
    source = SourceBinding.model_validate(row["binding"])
    async with postgres_service(dsn, OfflineAnalyzer()) as service:
        registry = service._registry
        try:
            async with registry.locked(identity, source.task_id) as record:
                try:
                    snapshot = await service._snapshot(record)
                except InvalidTransition:
                    status = "material_contract_mismatch"
                else:
                    status = material_status(source, snapshot.values)
                    if await registry.pending(source.task_id):
                        status = "material_pending"
                return await store.finish(registry.conn, identity, receipt_id, status)
        except AccessDenied:
            return await store.finish(registry.conn, identity, receipt_id, "task_unavailable")
