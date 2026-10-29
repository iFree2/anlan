"""Authenticated HTTP and latest-snapshot SSE conversation adapters."""

import re
from typing import Annotated, Literal

from fastapi import Header, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from anlan.common.models import StrictModel
from anlan.conversation.contracts import CollaborationInput, IntentProposal
from anlan.interfaces.streams import snapshot_stream
from anlan.workflows.event_contracts import Identifier


class CreateConversationRequest(StrictModel):
    request_id: Identifier


class BindTaskRequest(StrictModel):
    task_id: Identifier
    expected_revision: int = Field(strict=True, ge=1)


class CollaborationCandidateRequest(StrictModel):
    request_id: Identifier
    expected_revision: int = Field(strict=True, ge=1)
    intent: Literal['submit_application', 'request_changes', 'resubmit_application',
                    'complete_material_review']
    collaboration: CollaborationInput


class HumanCitationCandidateRequest(StrictModel):
    """A safety manager's actual checkbox selection; never a model-proposed field."""
    request_id: Identifier
    expected_revision: int = Field(strict=True, ge=1)
    expected_check_id: str = Field(strict=True, min_length=1, max_length=500)
    expected_material_revision: int = Field(strict=True, ge=1)
    expected_binding_revision: int = Field(strict=True, ge=1)
    expected_application_version: int = Field(strict=True, ge=1)
    conclusion: str = Field(strict=True, min_length=1, max_length=500)
    applied_knowledge_citation_ids: list[str] = Field(min_length=1, max_length=3)


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
    @app.post('/conversations/{conversation_id}/task')
    async def bind_task(conversation_id: str, payload: BindTaskRequest, identity: Actor):
        return await service.bind(identity, conversation_id, **payload.model_dump())

    @app.post('/conversations/{conversation_id}/collaboration-candidates')
    async def candidate(conversation_id: str, payload: CollaborationCandidateRequest,
                        identity: Actor):
        proposal = IntentProposal(intent=payload.intent, collaboration=payload.collaboration,
                                  requires_confirmation=True, user_explanation='本人结构化选择',
                                  classifier_version='structured-collaboration-v1')
        return await service.message(identity, conversation_id, request_id=payload.request_id,
                                     expected_revision=payload.expected_revision,
                                     text={'submit_application': '准备提交申请',
                                           'request_changes': '准备提出补充要求',
                                           'resubmit_application': '准备重新提交申请',
                                           'complete_material_review': '准备完成人工材料核查'}[
                                               payload.intent], proposal_override=proposal)

    @app.post('/conversations/{conversation_id}/preflight-citation-candidates')
    async def human_citation_candidate(conversation_id: str, payload: HumanCitationCandidateRequest,
                                       identity: Actor):
        # This route is a deterministic human selection, not a classifier tool call.
        proposal = IntentProposal(
            intent='complete_material_review',
            collaboration=CollaborationInput(
                conclusion=payload.conclusion,
                applied_knowledge_citation_ids=payload.applied_knowledge_citation_ids,
                expected_check_id=payload.expected_check_id,
                expected_material_revision=payload.expected_material_revision,
                expected_binding_revision=payload.expected_binding_revision,
                expected_application_version=payload.expected_application_version,
            ),
            requires_confirmation=True,
            user_explanation='本人已选择本轮实际采用的预核查引用',
            classifier_version='structured-human-citations-v1',
        )
        return await service.message(
            identity, conversation_id, request_id=payload.request_id,
            expected_revision=payload.expected_revision, text='准备确认实际采用的作业前依据',
            proposal_override=proposal,
        )
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
