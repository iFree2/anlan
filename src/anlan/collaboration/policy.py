"""Pure authorization: trusted role, explicit participant, then legal stage."""

from anlan.collaboration.contracts import Action, ApplicationRecord, Role
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity

_READS = {"read", "read_events"}
_APPLICANT = _READS | {"edit_materials", "submit", "resubmit"}
_REVIEWER = _READS | {
    "request_changes", "complete_review", "run_event_review", "record_event_feedback",
}
_STAGES = {
    "edit_materials": {"draft", "changes_requested"},
    "submit": {"draft"},
    "resubmit": {"changes_requested"},
    "request_changes": {"under_review"},
    "complete_review": {"under_review"},
}


def authorize(
    actor: Identity, role: Role | None, application: ApplicationRecord, action: Action,
) -> None:
    if actor.tenant_id != application.tenant_id:
        raise AccessDenied("申请不存在或当前身份无权访问")
    if role == "applicant" and actor.user_id == application.applicant_user_id:
        allowed = _APPLICANT
    elif (
        role == "safety_manager"
        and actor.user_id == application.reviewer_user_id
        and actor.user_id != application.applicant_user_id
        and application.status != "draft"
    ):
        allowed = _REVIEWER
    else:
        raise AccessDenied("申请不存在或当前身份无权访问")
    if action not in allowed:
        raise AccessDenied("当前身份无权执行该动作")
    if action in _STAGES and application.status not in _STAGES[action]:
        raise InvalidTransition("当前申请阶段不允许该动作")
