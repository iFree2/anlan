"""Opt-in synthetic role tokens never relax ordinary service credentials."""
from importlib.resources import files
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from test_events_postgres import dsn, run  # noqa: F401 -- explicit local PG

from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig, TokenGrant
from anlan.knowledge.tool import UnavailableKnowledgeStore


def demo_grant(**changes):
    return {"token": "demo123", "demo_short_token": True,
            "identity": {"tenant_id": "synthetic-short-login", "user_id": "applicant"},
            "collaboration_role": "applicant"} | changes


def service(*grants, **changes):
    return ServiceConfig.model_validate({"schema_version": "local-service-v1",
        "as_of": "2026-09-22T04:00:00Z", "tokens": list(grants)} | changes)


def test_short_token_requires_explicit_marker_and_default_long_token_still_works():
    assert service(demo_grant()).tokens[0].demo_short_token is True
    with pytest.raises(ValidationError):
        service(demo_grant(demo_short_token=False))
    value = demo_grant()
    value.pop("demo_short_token")
    with pytest.raises(ValidationError):
        TokenGrant.model_validate(value)
    assert service(value | {"token": "a" * 32}).tokens[0].demo_short_token is False


@pytest.mark.parametrize("changes", [
    {"identity": {"tenant_id": "enterprise", "user_id": "applicant"}},
    {"collaboration_role": None},
    {"demo_short_token": "true"},
    {"token": "sixsix"}, {"token": "bad token"}, {"token": "a" * 257},
    {"token": "中文测试口令"},
])
def test_demo_short_token_rejects_out_of_scope_or_invalid_configuration(changes):
    with pytest.raises(ValidationError):
        service(demo_grant(**changes))


def test_demo_short_token_requires_fixed_replay_clock():
    with pytest.raises(ValidationError):
        service(demo_grant(), as_of=None)


def test_role_tokens_must_remain_unique_and_legacy_strong_grant_stays_private():
    manager = demo_grant(identity={"tenant_id": "synthetic-short-login", "user_id": "manager"},
                         collaboration_role="safety_manager")
    with pytest.raises(ValidationError, match="unique"):
        service(demo_grant(), manager)
    legacy = {"token": "l" * 64, "identity": {"tenant_id": "legacy", "user_id": "owner"}}
    config = service(demo_grant(), manager | {"token": "demo4567"}, legacy)
    assert config.tokens[-1].collaboration_role is None
    assert config.tokens[-1].demo_short_token is False


def test_console_accepts_short_token_syntax_but_reports_demo_risk():
    script = files("anlan.interfaces.console").joinpath("assets/app.js").read_text("utf-8")
    assert "/^[A-Za-z0-9._~-]{7,256}$/" in script
    assert "state.info.demo_short_token" in script
    assert "演示短口令" in script


@pytest.mark.postgres
def test_short_token_http_roles_and_private_conversation_isolation(dsn):  # noqa: F811
    async def scenario():
        tenant = "synthetic-short-" + uuid4().hex
        applicant = demo_grant(identity={"tenant_id": tenant, "user_id": "applicant"})
        manager = demo_grant(token="demo4567", identity={"tenant_id": tenant, "user_id": "manager"},
                             collaboration_role="safety_manager")
        config = service(applicant, manager)
        app = create_app(dsn, config, knowledge=UnavailableKnowledgeStore())
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ids = []
            for grant in (applicant, manager):
                headers = {"Authorization": "Bearer " + grant["token"]}
                response = await client.get("/console/api/info", headers=headers)
                assert response.status_code == 200
                info = response.json()
                assert info["identity"] == grant["identity"]
                assert info["collaboration_role"] == grant["collaboration_role"]
                assert info["demo_short_token"] is True
                assert grant["token"] not in response.text
                created = await client.post("/conversations", headers=headers,
                                            json={"request_id": uuid4().hex})
                assert created.status_code == 200
                ids.append(created.json()["conversation_id"])
            for index, grant in enumerate((applicant, manager)):
                response = await client.get("/conversations/" + ids[1-index],
                    headers={"Authorization": "Bearer " + grant["token"]})
                assert response.status_code == 404
            for token in (None, "wrong12", "a" * 64):
                response = await client.get("/console/api/info",
                    headers={"Authorization": "Bearer " + token} if token else {})
                assert response.status_code == 401
    run(scenario())
