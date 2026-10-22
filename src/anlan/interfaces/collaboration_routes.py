"""Authenticated collaboration HTTP; no client actor/role/storage-scope parameters."""

from fastapi import Query

from anlan.collaboration.service import (
    CompleteReviewCommand,
    RequestChangesCommand,
    ResubmitCommand,
    SubmitCommand,
)


def install_collaboration_routes(app, service, Actor):
    @app.get("/collaboration/applications")
    async def applications(identity: Actor):
        return await service.list(identity)

    @app.get("/collaboration/applications/{task_id}")
    async def application(task_id: str, identity: Actor):
        return await service.get(identity, task_id)

    @app.post("/collaboration/applications/{task_id}/commands/submit")
    async def submit(task_id: str, payload: SubmitCommand, identity: Actor):
        return await service.execute(identity, task_id, "submit", payload.model_dump())

    @app.post("/collaboration/applications/{task_id}/commands/request_changes")
    async def request_changes(task_id: str, payload: RequestChangesCommand, identity: Actor):
        return await service.execute(identity, task_id, "request_changes", payload.model_dump())

    @app.post("/collaboration/applications/{task_id}/commands/resubmit")
    async def resubmit(task_id: str, payload: ResubmitCommand, identity: Actor):
        return await service.execute(identity, task_id, "resubmit", payload.model_dump())

    @app.post("/collaboration/applications/{task_id}/commands/complete_review")
    async def complete_review(task_id: str, payload: CompleteReviewCommand, identity: Actor):
        return await service.execute(identity, task_id, "complete_review", payload.model_dump())

    @app.get("/collaboration/notifications")
    async def notifications(identity: Actor, after: int = Query(default=0, ge=0),
                            limit: int = Query(default=100, ge=1, le=100)):
        return await service.notifications(identity, after=after, limit=limit)
