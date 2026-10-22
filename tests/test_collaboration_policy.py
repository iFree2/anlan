"""Every role/state/action combination is checked without IO."""

from itertools import product
from typing import get_args

import pytest
from pydantic import ValidationError

from anlan.collaboration.contracts import Action, ApplicationRecord, ApplicationStatus, Role
from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity

APPLICANT = Identity(tenant_id="tenant", user_id="applicant")
REVIEWER = Identity(tenant_id="tenant", user_id="reviewer")
READS = {"read", "read_events"}
APPLICANT_ACTIONS = READS | {"edit_materials", "submit", "resubmit"}
REVIEWER_ACTIONS = READS | {
    "request_changes", "complete_review", "run_event_review", "record_event_feedback",
}


def application(status="draft"):
    return ApplicationRecord(
        task_id="task", tenant_id="tenant", applicant_user_id="applicant",
        reviewer_user_id=None if status == "draft" else "reviewer", status=status, version=1,
        submitted_material_revision=None if status == "draft" else 2,
        completed_material_revision=2 if status == "review_completed" else None,
    )


@pytest.mark.parametrize("role,status,action", list(product(
    get_args(Role), get_args(ApplicationStatus), get_args(Action),
)))
def test_role_state_action_matrix(role, status, action):
    actor = APPLICANT if role == "applicant" else REVIEWER
    permitted = APPLICANT_ACTIONS if role == "applicant" else REVIEWER_ACTIONS
    if action not in permitted or (role == "safety_manager" and status == "draft"):
        expected = AccessDenied
    elif action in READS:
        expected = None
    elif action == "edit_materials":
        expected = None if status in {"draft", "changes_requested"} else InvalidTransition
    elif action == "submit":
        expected = None if status == "draft" else InvalidTransition
    elif action == "resubmit":
        expected = None if status == "changes_requested" else InvalidTransition
    elif action in {"request_changes", "complete_review"}:
        expected = None if status == "under_review" else InvalidTransition
    else:
        expected = None  # assigned event review/feedback is available after first submission
    if expected:
        with pytest.raises(expected):
            authorize(actor, role, application(status), action)
    else:
        assert authorize(actor, role, application(status), action) is None


@pytest.mark.parametrize("action", get_args(Action))
@pytest.mark.parametrize("actor,role", [
    (Identity(tenant_id="foreign", user_id="applicant"), "applicant"),
    (Identity(tenant_id="tenant", user_id="unassigned"), "safety_manager"),
    (Identity(tenant_id="tenant", user_id="another-applicant"), "applicant"),
    (APPLICANT, "safety_manager"), (REVIEWER, "applicant"), (APPLICANT, None),
])
def test_cross_tenant_unassigned_self_review_and_legacy_denied(actor, role, action):
    with pytest.raises(AccessDenied):
        authorize(actor, role, application("under_review"), action)


@pytest.mark.parametrize("changes", [
    {"version": 0}, {"version": True}, {"version": "1"}, {"status": "approved"},
    {"task_id": ""}, {"role": "applicant"},
    {"reviewer_user_id": "applicant"}, {"submitted_material_revision": 0},
    {"submitted_material_revision": None}, {"completed_material_revision": 2},
    {"status": "review_completed", "completed_material_revision": 1},
])
def test_strict_application_contract_rejects_invalid_state(changes):
    with pytest.raises(ValidationError):
        ApplicationRecord.model_validate(application("under_review").model_dump() | changes)
