"""Authenticated, typed B3 HTTP boundary for trusted preflight operations."""

from anlan.preflight.bindings import BindingService
from anlan.preflight.contracts import BindingCommand, RecheckCommand


def install_preflight_routes(app, collaboration, Actor):
    """Install only deterministic commands; identity is always supplied by ``who``."""

    def bindings():
        return BindingService(
            collaboration.prechecks.dsn,
            collaboration.config,
            collaboration.service_context_factory,
        )

    @app.get("/collaboration/applications/{task_id}/object-catalog")
    async def object_catalog(task_id: str, identity: Actor):
        return await bindings().catalog(identity, task_id)

    @app.get("/collaboration/applications/{task_id}/binding")
    async def binding(task_id: str, identity: Actor):
        return await bindings().get(identity, task_id)

    @app.post("/collaboration/applications/{task_id}/binding")
    async def confirm_binding(task_id: str, payload: BindingCommand, identity: Actor):
        return await bindings().confirm(identity, task_id, payload.model_dump())

    @app.get("/collaboration/applications/{task_id}/prechecks")
    async def prechecks(task_id: str, identity: Actor):
        return (await collaboration.get(identity, task_id))["precheck"]

    @app.post("/collaboration/applications/{task_id}/prechecks")
    async def recheck(task_id: str, payload: RecheckCommand, identity: Actor):
        # The application-owned service has the durable worker/clock configuration.
        return await collaboration._bounded_lock(
            lambda: app.state.preflight.recheck(identity, task_id, payload.model_dump())
        )
