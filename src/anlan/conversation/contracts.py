"""Strict model-facing and persisted conversation contracts."""

from typing import Literal

from pydantic import Field

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
]
ConversationStatus = Literal["idle", "pending_confirmation", "active_hot_work", "paused"]


class PendingIntent(StrictModel):
    intent_id: NonEmpty
    kind: Literal["hot_work_candidate", "task_input_candidate", "switch_or_create_task"]
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    revision: int = Field(strict=True, ge=1)


class ConversationState(StrictModel):
    conversation_id: NonEmpty
    revision: int = Field(strict=True, ge=1)
    status: ConversationStatus = "idle"
    active_task_id: NonEmpty | None = None
    pending_intent: PendingIntent | None = None


class IntentProposal(StrictModel):
    intent: IntentKind
    fields: dict[FieldName, Text] = Field(default_factory=dict, max_length=4)
    requires_confirmation: bool = False
    target_task_id: NonEmpty | None = None
    user_explanation: NonEmpty
    classifier_version: NonEmpty
