"""Collaboration roles are host configuration, never client identity fields."""

import pytest
from pydantic import ValidationError

from anlan.common.models import Identity
from anlan.interfaces.service_config import ServiceConfig, TokenGrant

APPLICANT = Identity(tenant_id="tenant", user_id="applicant")
REVIEWER = Identity(tenant_id="tenant", user_id="reviewer")


def grant(identity, role=None, token="a"):
    return {"token": token * 64, "identity": identity.model_dump(), "collaboration_role": role}


def config(*tokens):
    return ServiceConfig.model_validate({"schema_version": "local-service-v1", "tokens": tokens})


def test_legacy_grant_defaults_to_no_collaboration_role():
    legacy = TokenGrant(token="a" * 64, identity=APPLICANT)
    assert legacy.collaboration_role is None
    assert config(legacy).collaboration_role(APPLICANT) is None


def test_explicit_roles_and_same_tenant_reviewer_directory():
    foreign = Identity(tenant_id="foreign", user_id="reviewer")
    service = config(
        grant(APPLICANT, "applicant"), grant(REVIEWER, "safety_manager", "b"),
        grant(REVIEWER, "safety_manager", "c"), grant(foreign, "safety_manager", "d"),
    )
    assert service.collaboration_role(APPLICANT) == "applicant"
    assert service.collaboration_role(REVIEWER) == "safety_manager"
    assert service.collaboration_role(Identity(tenant_id="tenant", user_id="unknown")) is None
    assert service.collaboration_reviewers(APPLICANT) == [REVIEWER]
    assert "token" not in str(service.collaboration_reviewers(APPLICANT))


@pytest.mark.parametrize("roles", [("applicant", "safety_manager"), (None, "applicant")])
def test_same_identity_cannot_have_contradictory_roles(roles):
    with pytest.raises(ValidationError, match="Conflicting collaboration roles"):
        config(grant(APPLICANT, roles[0]), grant(APPLICANT, roles[1], "b"))


@pytest.mark.parametrize("role", ["admin", "approved", "", 1])
def test_invalid_role_is_rejected(role):
    with pytest.raises(ValidationError):
        config(grant(APPLICANT, role))


@pytest.mark.parametrize("field", ["role", "collaboration_role", "actor", "reviewer_user_id"])
def test_client_identity_cannot_inject_authority(field):
    with pytest.raises(ValidationError):
        Identity.model_validate(APPLICANT.model_dump() | {field: "safety_manager"})
