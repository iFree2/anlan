"""Strict collaboration metadata; material and conversation state remain separate."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from anlan.common.models import NonEmpty, StrictModel

Role = Literal["applicant", "safety_manager"]
ApplicationStatus = Literal["draft", "under_review", "changes_requested", "review_completed"]
Action = Literal[
    "read", "edit_materials", "submit", "request_changes", "resubmit", "complete_review",
    "read_events", "run_event_review", "record_event_feedback",
]
PositiveVersion = Annotated[int, Field(strict=True, ge=1)]


class ApplicationRecord(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: NonEmpty
    tenant_id: NonEmpty
    applicant_user_id: NonEmpty
    reviewer_user_id: NonEmpty | None = None
    status: ApplicationStatus = "draft"
    version: PositiveVersion = 1
    submitted_material_revision: PositiveVersion | None = None
    completed_material_revision: PositiveVersion | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def consistent_stage(self):
        if self.reviewer_user_id == self.applicant_user_id:
            raise ValueError("Applicant cannot review their own application")
        if self.status == "draft":
            if self.reviewer_user_id is not None or self.submitted_material_revision is not None:
                raise ValueError("Draft has no assigned reviewer or submitted material revision")
        elif self.reviewer_user_id is None or self.submitted_material_revision is None:
            raise ValueError("Submitted application needs a reviewer and material revision")
        if self.status == "review_completed":
            if self.completed_material_revision != self.submitted_material_revision:
                raise ValueError("Completion must reference the submitted material revision")
        elif self.completed_material_revision is not None:
            raise ValueError("Only completed review has a completed material revision")
        return self
