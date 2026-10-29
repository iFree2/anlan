"""Local FastAPI adapter: trusted identity, bounded bodies, existing persistent workflows."""

import asyncio
import re
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, ValidationError

from anlan.collaboration.event_access import public_event, public_review
from anlan.collaboration.service import CollaborationService
from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity, StrictModel
from anlan.conversation.service import ConversationService
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.infrastructure.conversations import ConversationStore
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.perception import PerceptionStore
from anlan.infrastructure.postgres import initialize_database
from anlan.infrastructure.preflight import PrecheckStore
from anlan.interfaces.collaboration_conversation import CollaborationConversationAdapter
from anlan.interfaces.collaboration_routes import install_collaboration_routes
from anlan.interfaces.console.routes import install_console
from anlan.interfaces.console.service import ConsoleService
from anlan.interfaces.conversation_routes import install_conversation_routes
from anlan.interfaces.conversation_runtime import WorkflowAdapter
from anlan.interfaces.event_runtime import process_event
from anlan.interfaces.perception_runtime import Feedback, PerceptionRuntime
from anlan.interfaces.preflight_routes import install_preflight_routes
from anlan.interfaces.service_models import ServiceModels
from anlan.interfaces.streams import snapshot_stream
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.knowledge.tool import UnavailableKnowledgeStore
from anlan.llm.perception import ScriptedPerceptionModel
from anlan.memory.store import MemoryStore
from anlan.preflight.runner import PreflightRunner
from anlan.preflight.service import PreflightService
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
    events = EventStore(dsn, clock=clock, access_config=config)
    memory = MemoryStore(dsn, clock=clock)
    conversations = ConversationStore(dsn)
    sources = config

    @asynccontextmanager
    async def lifespan(app):
        await initialize_database(dsn)
        await CollaborationStore(dsn).initialize()
        await events.initialize()
        await PerceptionStore(dsn).initialize()
        await ConsoleService(dsn, config, clock=clock).initialize()
        await memory.initialize()
        await conversations.initialize()
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
        prechecks = PrecheckStore(dsn)
        # Explicit, persisted upgrade: completed rows stay historical; all unfinished
        # collaboration rows require evidence. No private task is registered or queried.
        async with prechecks.connection() as conn:
            rows = await (await conn.execute(
                'SELECT a.task_id,a.tenant_id FROM anlan_v2.collaboration_applications a '
                'LEFT JOIN anlan_v2.precheck_policies p USING(task_id) '
                'WHERE p.task_id IS NULL ORDER BY a.task_id')).fetchall()
            for row in rows:
                async with conn.transaction():
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                                       (row['task_id'],))
                    await prechecks.ensure_policy(row['tenant_id'], row['task_id'], conn=conn)
        app.state.preflight = PreflightService(dsn, config, models.material_service,
            PreflightRunner(FactTools(config.facts_dir, clock=clock), selected, clock=clock),
            clock=clock)
        async with models.lifespan():
            worker = asyncio.create_task(app.state.preflight.serve())
            try:
                yield
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

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

    async def legacy_actor(identity: Actor):
        # Raw source ingestion stays legacy-only; collaboration uses trusted console bindings.
        if config.collaboration_role(identity) is not None:
            raise AccessDenied("当前角色事件能力尚未接入")
        return identity

    LegacyActor = Annotated[Identity, Depends(legacy_actor)]

    async def event_actor(identity: Actor):
        role = config.collaboration_role(identity)
        if role is not None and (role != 'safety_manager' or not config.console_profile(identity)):
            raise AccessDenied('当前身份未配置事件操作权限')
        return identity

    EventActor = Annotated[Identity, Depends(event_actor)]

    def event_view(identity, value):
        return public_event(value) if config.collaboration_role(identity) else value

    def review_view(identity, value):
        return public_review(value) if config.collaboration_role(identity) else value
    collaboration = CollaborationService(dsn, config, models.material_service)
    conversation_service = ConversationService(conversations, models.conversation,
        CollaborationConversationAdapter(collaboration, WorkflowAdapter(models.material_service)))

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
            access_config=config,
        )

    async def task_read(identity, task):
        async with models.material_service() as service:
            return await CollaborationService._bounded_lock(lambda: service.get(identity, task))

    install_conversation_routes(app, conversation_service, Actor)
    collaboration_routes = CollaborationService(dsn, config, models.material_service)
    install_collaboration_routes(app, collaboration_routes, Actor)
    install_preflight_routes(app, collaboration_routes, Actor)

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
            return await CollaborationService._bounded_lock(lambda: service.history(identity, task))

    @app.post("/tasks/{task}/recover")
    async def recover_task(task: str, identity: Actor):
        async with models.material_service() as service:
            return await CollaborationService._bounded_lock(lambda: service.recover(identity, task))

    @app.post("/tasks/{task}/{action}")
    async def submit(
        task: str, action: Literal["resume", "revise"], payload: SubmitRequest, identity: Actor
    ):
        async with models.material_service() as service:
            method = service.resume if action == "resume" else service.revise
            return await CollaborationService._bounded_lock(lambda: method(
                identity,
                task,
                payload.expected_revision,
                payload.fields,
                request_id=payload.request_id,
            ))

    @app.post("/sources/{source_id}/events")
    async def receive_event(source_id: str, payload: dict, identity: LegacyActor):
        source = sources.source(identity, source_id)
        return await events.receive(
            identity, source_id, payload, source.binding if source else None
        )

    @app.get("/events/{receipt}")
    async def show_event(receipt: str, identity: Actor):
        return event_view(identity, await events.get(identity, receipt))

    @app.post("/events/{receipt}/process")
    async def associate(receipt: str, identity: EventActor):
        return event_view(identity, await process_event(dsn, identity, receipt, clock=clock,
                                                        access_config=config))

    @app.post("/events/{receipt}/reviews")
    async def review(receipt: str, payload: ReviewRequest, identity: EventActor):
        if config.collaboration_role(identity):
            value = await ConsoleService(dsn, config, clock=clock).review(
                identity, receipt, payload.request_id, perception())
            return review_view(identity, value)
        event = await events.get(identity, receipt)
        source = sources.source(identity, event["source_id"])
        if source is None:
            raise InvalidTransition("No trusted source configuration")
        return await perception().review(
            identity, receipt, source.references.model_dump(), request_id=payload.request_id
        )

    @app.get("/reviews/{review_id}")
    async def show_review(review_id: str, identity: Actor):
        return review_view(identity, await perception().get(identity, review_id))

    @app.post("/reviews/{review_id}/feedback")
    async def feedback(review_id: str, payload: Feedback, identity: EventActor):
        return review_view(identity, await perception().feedback(
            identity,
            review_id,
            payload.expected_revision,
            payload.decision,
            request_id=payload.request_id,
        ))

    @app.post("/reviews/{review_id}/{action}")
    async def control(review_id: str, action: Literal["recover", "cancel"], identity: EventActor):
        method = perception().recover if action == "recover" else perception().cancel
        return review_view(identity, await method(identity, review_id))

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
                return event_view(identity, await events.get(identity, key))
            return review_view(identity, await perception().get(identity, key))

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
