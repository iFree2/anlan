"""Compose event association with the existing task lock and checkpoint connection."""
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.preflight import PrecheckStore
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.event_contracts import SourceBinding
from anlan.workflows.events import material_status
from anlan.workflows.material_analysis import OfflineAnalyzer


async def process_event(dsn, identity, receipt_id, *, clock=None, access_config=None):
    store = EventStore(dsn, clock=clock, access_config=access_config)
    row = await store.get(identity, receipt_id)  # Event ownership before task/checkpoint access.
    async with await store.connect() as conn:
        await store.access.resource(conn, identity, receipt_id, action='run_event_review')
    if row["result"] is not None:
        return row
    source = SourceBinding.model_validate(row["binding"])
    async with postgres_service(dsn, OfflineAnalyzer(), access_config=access_config) as service:
        registry = service._registry
        try:
            async with registry.locked(identity, source.task_id,
                                       action='run_event_review') as record:
                try:
                    snapshot = await service._snapshot(record)
                except InvalidTransition:
                    status = "material_contract_mismatch"
                else:
                    status = material_status(source, snapshot.values)
                    application = await registry.access.application(registry.conn, source.task_id)
                    if application is not None:
                        binding = await PrecheckStore(dsn).get_binding(
                            identity.tenant_id, source.task_id, conn=registry.conn
                        )
                        if (
                            binding is None
                            or source.binding_revision is None
                            or binding.binding_revision != source.binding_revision
                            or binding.references.area_id != source.object_ref
                        ):
                            status = "stale_binding"
                    if await registry.pending(source.task_id):
                        status = "material_pending"
                return await store.finish(registry.conn, identity, receipt_id, status)
        except AccessDenied:
            return await store.finish(registry.conn, identity, receipt_id, "task_unavailable")
