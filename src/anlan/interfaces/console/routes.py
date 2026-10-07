"""Same-origin assets and authenticated adapters for the local synthetic console."""

from importlib.resources import files
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import Field

from anlan.common.models import Identity, StrictModel
from anlan.interfaces.console.service import ConsoleService
from anlan.workflows.event_contracts import EventKind, Identifier


class SimulateRequest(StrictModel):
    request_id: Identifier
    expected_revision: int = Field(strict=True, ge=1)
    kind: EventKind


class ConsoleReviewRequest(StrictModel):
    request_id: Identifier


HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def install_console(app, dsn, config, who, clock, runtime_factory):
    service = ConsoleService(dsn, config, clock=clock)
    Actor = Annotated[Identity, Depends(who)]
    assets = files("anlan.interfaces.console").joinpath("assets")

    @app.get("/console", include_in_schema=False)
    async def shell(request: Request):
        prefix = request.scope.get("root_path", "")
        html = assets.joinpath("index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace('"/console/', '"' + prefix + '/console/'),
                            headers=HEADERS)

    @app.get("/console/assets/{name}", include_in_schema=False)
    async def asset(name: str):
        allowed = {"app.js": "text/javascript", "api.js": "text/javascript",
                   "styles.css": "text/css"}
        if name not in allowed:
            raise HTTPException(404)
        return Response(assets.joinpath(name).read_bytes(), media_type=allowed[name],
                        headers=HEADERS)

    @app.get("/console/api/info")
    async def info(identity: Actor):
        profile = config.console_profile(identity)
        return {"identity": identity.model_dump(), "data_origin": "SYNTHETIC",
                "material_mode": "offline", "model_mode": "scripted_double",
                "simulation_enabled": profile is not None,
                "references": profile.references.model_dump() if profile else None,
                "as_of": clock().isoformat()}

    @app.get("/console/api/tasks")
    async def tasks(identity: Actor):
        return await service.tasks(identity)

    @app.get("/console/api/tasks/{task}/events")
    async def events(task: str, identity: Actor):
        return await service.list_events(identity, task)

    @app.post("/console/api/tasks/{task}/events")
    async def simulate(task: str, payload: SimulateRequest, identity: Actor):
        return await service.simulate(identity, task, payload)

    @app.get("/console/api/events/{receipt}/reviews")
    async def reviews(receipt: str, identity: Actor):
        return await service.reviews(identity, receipt)

    @app.post("/console/api/events/{receipt}/reviews")
    async def review(receipt: str, payload: ConsoleReviewRequest, identity: Actor):
        return await service.review(identity, receipt, payload.request_id, runtime_factory())
