"""Strict model-facing and persisted conversation contracts."""

from typing import Literal

from pydantic import Field, model_validator

from anlan.collaboration.service import COMMANDS, CommandText
from anlan.common.models import NonEmpty, StrictModel
from anlan.workflows.material_contracts import FieldName, Text

IntentKind = Literal[
    "casual_chat",
    "hot_work_candidate",
    "confirm_pending_intent",
    "reject_pending_intent",
    "task_input_candidate",
    "pause_task",
    "resume_task",
    "cancel_task",
    "switch_or_create_task",
    "switch_task",
    "submit_application",
    "request_changes",
    "resubmit_application",
    "complete_material_review",
    "query_application_status",
    "query_application_details",
    "query_process_guidance",
    "query_safety_knowledge",
]
BUSINESS_QUERY_INTENTS = {
    "query_application_status": "application_status",
    "query_application_details": "application_details",
    "query_process_guidance": "process_guidance",
    "query_safety_knowledge": "safety_knowledge",
}
COLLABORATION_INTENTS = {
    'submit_application': 'submit', 'request_changes': 'request_changes',
    'resubmit_application': 'resubmit', 'complete_material_review': 'complete_review',
}


class CollaborationInput(StrictModel):
    reviewer_user_id: CommandText | None = None
    questions: list[CommandText] = Field(default_factory=list, max_length=20)
    reply: CommandText | None = None
    conclusion: CommandText | None = None
    applied_knowledge_citation_ids: list[CommandText] = Field(default_factory=list, max_length=3)
    expected_check_id: CommandText | None = None
    expected_material_revision: int | None = Field(default=None, strict=True, ge=1)
    expected_binding_revision: int | None = Field(default=None, strict=True, ge=1)
    expected_application_version: int | None = Field(default=None, strict=True, ge=1)


class FrozenCollaborationCommand(StrictModel):
    task_id: NonEmpty
    action: Literal['submit', 'request_changes', 'resubmit', 'complete_review']
    payload: dict

    @model_validator(mode='after')
    def strict_command(self):
        COMMANDS[self.action].model_validate(self.payload)
        return self
ConversationStatus = Literal["idle", "pending_confirmation", "active_hot_work", "paused"]


class PendingIntent(StrictModel):
    intent_id: NonEmpty
    kind: Literal["hot_work_candidate", "task_input_candidate", "switch_or_create_task",
                  'submit_application', 'request_changes', 'resubmit_application',
                  'complete_material_review']
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    revision: int = Field(strict=True, ge=1)
    collaboration: FrozenCollaborationCommand | None = None


class ConversationState(StrictModel):
    conversation_id: NonEmpty
    revision: int = Field(strict=True, ge=1)
    status: ConversationStatus = "idle"
    active_task_id: NonEmpty | None = None
    pending_intent: PendingIntent | None = None


FollowUpIntent = Literal["task_input_candidate", "submit_application", "request_changes",
                         "resubmit_application", "complete_material_review"]


class QueryWriteCandidate(StrictModel):
    intent: FollowUpIntent
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    collaboration: CollaborationInput | None = None


class FrozenQueryFollowUp(StrictModel):
    intent: FollowUpIntent
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    collaboration: FrozenCollaborationCommand | None = None


class IntentProposal(StrictModel):
    intent: IntentKind
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    requires_confirmation: bool = False
    target_task_id: NonEmpty | None = None
    user_explanation: NonEmpty
    classifier_version: NonEmpty
    collaboration: CollaborationInput | None = None
    query_write: QueryWriteCandidate | None = None

    @model_validator(mode="after")
    def query_write_only_for_queries(self):
        if self.query_write is not None and self.intent not in BUSINESS_QUERY_INTENTS:
            raise ValueError("secondary writes require a query primary")
        return self
