"""Authenticated HTTP and latest-snapshot SSE conversation adapters."""

import re
from typing import Annotated

from fastapi import Header, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from anlan.common.models import StrictModel
from anlan.interfaces.streams import snapshot_stream
from anlan.workflows.event_contracts import Identifier


class CreateConversationRequest(StrictModel):
    request_id: Identifier


class ConversationMessageRequest(StrictModel):
    request_id: Identifier
    expected_revision: int = Field(strict=True, ge=1)
    text: str = Field(strict=True, min_length=1, max_length=8192)

    @field_validator("text")
    @classmethod
    def bounded_utf8(cls, value):
        value = value.strip()
        if not value or len(value.encode("utf-8")) > 8192:
            raise ValueError("message must contain between 1 and 8192 UTF-8 bytes")
        return value


def install_conversation_routes(app, service, Actor):
    @app.post("/conversations")
    async def create_conversation(payload: CreateConversationRequest, identity: Actor):
        return await service.create(identity, request_id=payload.request_id)

    @app.get("/conversations")
    async def list_conversations(identity: Actor):
        return await service.list(identity)

    @app.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, identity: Actor):
        return await service.snapshot(identity, conversation_id)

    @app.post("/conversations/{conversation_id}/messages")
    async def send_message(
        conversation_id: str,
        payload: ConversationMessageRequest,
        identity: Actor,
    ):
        return await service.message(
            identity,
            conversation_id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            text=payload.text,
        )

    @app.get("/conversations/{conversation_id}/stream")
    async def stream_conversation(
        conversation_id: str,
        request: Request,
        identity: Actor,
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        if last_event_id is not None and not re.fullmatch(r"[a-f0-9]{64}", last_event_id):
            raise ValueError("Invalid snapshot cursor")

        async def read():
            return await service.snapshot(identity, conversation_id)

        initial = await read()
        return StreamingResponse(
            snapshot_stream(initial, read, last_event_id, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
