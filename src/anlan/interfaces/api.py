"""Local FastAPI adapter: trusted identity, bounded bodies, existing persistent workflows."""

import re
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, ValidationError

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity, StrictModel
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.perception import PerceptionStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.console.routes import install_console
from anlan.interfaces.console.service import ConsoleService
from anlan.interfaces.event_runtime import process_event
from anlan.interfaces.perception_runtime import Feedback, PerceptionRuntime
from anlan.interfaces.service_models import ServiceModels
from anlan.interfaces.streams import snapshot_stream
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.knowledge.tool import UnavailableKnowledgeStore
from anlan.llm.perception import ScriptedPerceptionModel
from anlan.memory.store import MemoryStore
from anlan.tools.queries import FactTools
from anlan.workflows.event_contracts import Identifier
from anlan.workflows.material_contracts import Application, Supplement
from anlan.workflows.service import start_task_id


class StartRequest(StrictModel):
    request_id: Identifier
    fields: Application


class SubmitRequest(Supplement):
    request_id: Identifier
    expected_revision: int = Field(strict=True, ge=1)


class ReviewRequest(StrictModel):
    request_id: Identifier


class BoundedBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 32768:
                return await JSONResponse({"error": "body_too_large"}, 413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)


def create_app(dsn, config, *, knowledge=None, model_factory=ScriptedPerceptionModel,
               root_path="", model_config=None, model_transport=None, budget_ledger=None):
    models = ServiceModels(dsn, config, model_factory, model_config=model_config,
                           transport=model_transport, ledger=budget_ledger)
    if root_path and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", root_path):
        raise ValueError("Invalid trusted reverse proxy prefix")
    clock = lambda: config.as_of or datetime.now(UTC)  # noqa: E731
    events, memory = EventStore(dsn, clock=clock), MemoryStore(dsn, clock=clock)
    sources = config

    @asynccontextmanager
    async def lifespan(app):
        await initialize_database(dsn)
        await events.initialize()
        await PerceptionStore(dsn).initialize()
        await ConsoleService(dsn, config, clock=clock).initialize()
        await memory.initialize()
        await models.ledger.initialize()
        selected = knowledge
        if selected is None:
            try:
                selected = KnowledgeStore(
                    dsn, await LocalEmbeddings.create(config.embeddings_cache), clock=clock
                )
                await selected.initialize()
            except Exception:
                selected = UnavailableKnowledgeStore(clock)
        app.state.knowledge = selected
        async with models.lifespan():
            yield

    app = FastAPI(title="安澜 SYNTHETIC 本地服务", lifespan=lifespan, docs_url=None,
                  redoc_url=None, root_path=root_path)
    app.add_middleware(BoundedBody)

    async def who(authorization: Annotated[str | None, Header()] = None):
        if authorization is not None and authorization.startswith("Bearer "):
            token = authorization[7:].encode()
            for grant in sources.tokens:
                if secrets.compare_digest(token, grant.token.get_secret_value().encode()):
                    return grant.identity
        raise HTTPException(401, detail="authentication_required")

    Actor = Annotated[Identity, Depends(who)]

    async def safe_error(request, exc):
        if isinstance(exc, AccessDenied):
            return JSONResponse({"error": "not_found"}, 404)
        if isinstance(exc, (InvalidTransition, TaskBusy)):
            return JSONResponse({"error": "conflict_or_recovery_required"}, 409)
        if isinstance(exc, (ValueError, RequestValidationError, ValidationError)):
            return JSONResponse({"error": "invalid_request"}, 422)
        return JSONResponse({"error": "service_unavailable"}, 503)

    for error in (
        AccessDenied,
        InvalidTransition,
        TaskBusy,
        ValueError,
        RequestValidationError,
        ValidationError,
        psycopg.Error,
    ):
        app.add_exception_handler(error, safe_error)

    def perception(factory=None):
        return PerceptionRuntime(
            dsn,
            FactTools(config.facts_dir, clock=clock),
            app.state.knowledge,
            memory,
            factory() if factory else models.perception(),
            clock=clock,
        )

    async def task_read(identity, task):
        async with models.material_service() as service:
            return await service.get(identity, task)

    @app.get("/healthz")
    async def health():
        return {"status": "alive", "data_origin": "SYNTHETIC"}

    @app.get("/readyz")
    async def ready(identity: Actor):
        async with await events.connect() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ready", "data_origin": "SYNTHETIC",
                "model_mode": models.model_mode}

    @app.post("/tasks")
    async def start(payload: StartRequest, identity: Actor):
        async with models.material_service() as service:
            try:
                return await service.start(
                    identity, payload.fields.model_dump(), request_id=payload.request_id
                )
            except (InvalidTransition, TaskBusy):
                return JSONResponse(
                    {
                        "error": "conflict_or_recovery_required",
                        "task_id": start_task_id(identity, payload.request_id),
                    },
                    409,
                )

    @app.get("/tasks/by-request/{request_id}")
    async def by_request(request_id: str, identity: Actor):
        return await task_read(identity, start_task_id(identity, request_id))

    @app.get("/tasks/{task}")
    async def show_task(task: str, identity: Actor):
        return await task_read(identity, task)

    @app.get("/tasks/{task}/history")
    async def history(task: str, identity: Actor):
        async with models.material_service() as service:
            return await service.history(identity, task)

    @app.post("/tasks/{task}/recover")
    async def recover_task(task: str, identity: Actor):
        async with models.material_service() as service:
            return await service.recover(identity, task)

    @app.post("/tasks/{task}/{action}")
    async def submit(
        task: str, action: Literal["resume", "revise"], payload: SubmitRequest, identity: Actor
    ):
        async with models.material_service() as service:
            method = service.resume if action == "resume" else service.revise
            return await method(
                identity,
                task,
                payload.expected_revision,
                payload.fields,
                request_id=payload.request_id,
            )

    @app.post("/sources/{source_id}/events")
    async def receive_event(source_id: str, payload: dict, identity: Actor):
        source = sources.source(identity, source_id)
        return await events.receive(
            identity, source_id, payload, source.binding if source else None
        )

    @app.get("/events/{receipt}")
    async def show_event(receipt: str, identity: Actor):
        return await events.get(identity, receipt)

    @app.post("/events/{receipt}/process")
    async def associate(receipt: str, identity: Actor):
        return await process_event(dsn, identity, receipt, clock=clock)

    @app.post("/events/{receipt}/reviews")
    async def review(receipt: str, payload: ReviewRequest, identity: Actor):
        event = await events.get(identity, receipt)
        source = sources.source(identity, event["source_id"])
        if source is None:
            raise InvalidTransition("No trusted source configuration")
        return await perception().review(
            identity, receipt, source.references.model_dump(), request_id=payload.request_id
        )

    @app.get("/reviews/{review_id}")
    async def show_review(review_id: str, identity: Actor):
        return await perception().get(identity, review_id)

    @app.post("/reviews/{review_id}/feedback")
    async def feedback(review_id: str, payload: Feedback, identity: Actor):
        return await perception().feedback(
            identity,
            review_id,
            payload.expected_revision,
            payload.decision,
            request_id=payload.request_id,
        )

    @app.post("/reviews/{review_id}/{action}")
    async def control(review_id: str, action: Literal["recover", "cancel"], identity: Actor):
        method = perception().recover if action == "recover" else perception().cancel
        return await method(identity, review_id)

    @app.get("/{resource}/{key}/stream")
    async def stream(
        resource: Literal["tasks", "events", "reviews"],
        key: str,
        request: Request,
        identity: Actor,
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        if last_event_id is not None and not re.fullmatch(r"[a-f0-9]{64}", last_event_id):
            raise ValueError("Invalid snapshot cursor")

        async def read():
            if resource == "tasks":
                return await task_read(identity, key)
            if resource == "events":
                return await events.get(identity, key)
            return await perception().get(identity, key)

        initial = await read()  # Authorize and validate before sending response headers.
        return StreamingResponse(
            snapshot_stream(initial, read, last_event_id, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    install_console(app, dsn, config, who, clock,
                    lambda: perception() if models.live else perception(ScriptedPerceptionModel),
                    models.public_info)
    return app
