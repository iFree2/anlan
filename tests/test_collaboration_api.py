"""Two authenticated clients, real checkpoints and collaboration transactions."""

from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
import pytest
from test_events import NOW
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import COMPLETE, PATCH
from test_preflight_contracts import command as binding_command
from test_preflight_service import populate_sources

from anlan.common.models import Identity
from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig
from anlan.preflight.bindings import BindingService

pytestmark = pytest.mark.postgres


def settings():
    tenant = "b2-" + uuid4().hex
    actors = [
        Identity(tenant_id=tenant, user_id=user)
        for user in ("applicant", "reviewer", "unassigned", "other", "legacy")
    ]
    actors.append(Identity(tenant_id=tenant + "-foreign", user_id="reviewer"))
    roles = ["applicant", "safety_manager", "safety_manager", "applicant", None, "safety_manager"]
    tokens = [str(i) * 64 for i in range(1, 7)]
    config = ServiceConfig.model_validate(
        {
            "schema_version": "local-service-v1",
            "as_of": NOW,
            "tokens": [
                {"token": t, "identity": a.model_dump(), "collaboration_role": r}
                for t, a, r in zip(tokens, actors, roles)
            ],
        }
    )
    return config, actors, tokens


@asynccontextmanager
async def clients(dsn, config=None):  # noqa: F811
    config, actors, tokens = settings() if config is None else config
    with TemporaryDirectory(prefix="anlan-p13-") as directory:
        knowledge = await populate_sources(dsn, config, actors, Path(directory))
        app = create_app(dsn, config, knowledge=knowledge)
        async with app.router.lifespan_context(app):
            async with _sessions(app, tokens) as sessions:
                yield sessions, actors, config


@asynccontextmanager
async def _sessions(app, tokens):
    sessions = [
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + token},
        )
        for token in tokens
    ]
    try:
        yield sessions
    finally:
        for session in sessions:
            await session.aclose()


async def start(client, fields=None):
    response = await client.post(
        "/tasks", json={"request_id": uuid4().hex, "fields": COMPLETE if fields is None else fields}
    )
    assert response.status_code == 200, response.text
    state = response.json()
    app = client._transport.app
    config = app.state.preflight.config
    token = client.headers["Authorization"][7:]
    actor = next(g.identity for g in config.tokens if g.token.get_secret_value() == token)
    if config.collaboration_role(actor) == "applicant" and state["status"] == "awaiting_review":
        await BindingService(
            app.state.preflight.store.dsn, config, app.state.preflight.service_context_factory
        ).confirm(actor, state["task_id"], binding_command(request_id="bind-" + state["task_id"]))
    return state


def command(version=1, revision=1, **payload):
    return {
        "request_id": uuid4().hex,
        "expected_application_version": version,
        "expected_material_revision": revision,
        **payload,
    }


async def send(client, task, action, body, status=200):
    body = dict(body)
    if action in {"submit", "resubmit", "complete_review"}:
        body.setdefault("expected_binding_revision", 1)
    if action == "complete_review" and status == 200:
        body = await completion(client, task, body)
    response = await client.post(f"/collaboration/applications/{task}/commands/{action}", json=body)
    assert response.status_code == status, response.text
    return response.json()


async def completion(client, task, body):
    """P12 fixtures now explicitly obtain and choose real P13 evidence."""
    import asyncio

    app = client._transport.app
    async with asyncio.timeout(10):
        while True:
            job = await app.state.preflight.store.latest(
                app.state.preflight.config.tokens[0].identity.tenant_id, task
            )
            if job and job["result"] is not None:
                break
            if job:
                await app.state.preflight.process_next(job["job_id"])
            await asyncio.sleep(0.02)
    return {
        "expected_binding_revision": 1,
        "expected_check_id": job["check_id"],
        "applied_knowledge_citation_ids": job["result"]["citation_ids"],
        **body,
    }


def test_submit_return_resubmit_complete_same_task(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, _):
            applicant, reviewer = sessions[:2]
            state = await start(applicant)
            task = state["task_id"]
            path = f"/collaboration/applications/{task}"
            assert (await applicant.get(path)).json()["application"]["status"] == "draft"
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            assert len((await reviewer.get("/collaboration/applications")).json()["items"]) == 1
            shared = (await reviewer.get(path)).json()
            assert shared["materials"]["fields"] == COMPLETE
            assert "thread_id" not in str(shared) and "session_id" not in str(shared)
            await send(reviewer, task, "request_changes", command(2, questions=["明确具体点位"]))
            patch = await applicant.post(
                f"/tasks/{task}/revise",
                json={"request_id": "patch", "expected_revision": 1, "fields": PATCH},
            )
            assert patch.status_code == 200
            assert patch.json()["task_id"] == task and patch.json()["revision"] == 2
            await send(applicant, task, "resubmit", command(3, 2, reply="已更新方式说明"))
            result = await send(
                reviewer, task, "complete_review", command(4, 2, conclusion="已人工核对本轮材料")
            )
            assert result["application"]["status"] == "review_completed"
            assert result["application"]["version"] == 5
            assert result["application"]["completed_material_revision"] == 2
            timeline = (await applicant.get(path)).json()["events"]
            assert [e["action"] for e in timeline] == [
                "submit",
                "request_changes",
                "resubmit",
                "complete_review",
            ]
            assert [e["actor_user_id"] for e in timeline] == [
                a.user_id for a in (actors[0], actors[1], actors[0], actors[1])
            ]
            inbox = (await applicant.get("/collaboration/notifications")).json()
            assert [n["event"]["action"] for n in inbox["items"]] == [
                "request_changes",
                "complete_review",
            ]
            assert "approved" not in str(result) and "permit_issued" not in str(result)

    run(scenario())


@pytest.mark.parametrize("stage", ["under_review", "review_completed"])
def test_old_api_and_session_material_writes_are_frozen(dsn, stage):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            if stage == "review_completed":
                await send(reviewer, task, "complete_review", command(2, conclusion="已核对"))
            for action in ("resume", "revise", "recover"):
                response = await applicant.post(
                    f"/tasks/{task}/{action}",
                    json={"request_id": uuid4().hex, "expected_revision": 1, "fields": PATCH},
                )
                assert response.status_code == 409, response.text
            assert (
                await reviewer.post(
                    f"/tasks/{task}/revise",
                    json={"request_id": "forged", "expected_revision": 1, "fields": PATCH},
                )
            ).status_code == 404

    run(scenario())


def test_participants_legacy_and_strict_http_contract(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer, unassigned, other, legacy, foreign = sessions
            task = (await start(applicant))["task_id"]
            path = f"/collaboration/applications/{task}"
            for client in (reviewer, unassigned, other, legacy, foreign):
                assert (await client.get(path)).status_code == 404
            assert (
                await reviewer.post("/tasks", json={"request_id": "no", "fields": COMPLETE})
            ).status_code == 404
            for extra in ({"role": "safety_manager"}, {"actor": {"user_id": "reviewer"}}):
                await send(
                    applicant, task, "submit", command(reviewer_user_id="reviewer", **extra), 422
                )
            await send(applicant, task, "submit", command(reviewer_user_id="unconfigured"), 404)
            await send(applicant, task, "submit", command(reviewer_user_id="applicant"), 404)
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            await send(applicant, task, "complete_review", command(2, conclusion="fake"), 404)
            for client in (unassigned, other, legacy, foreign):
                assert (await client.get(path)).status_code == 404
                assert (await client.get(f"/tasks/{task}")).status_code == 404
            for action, payload in [
                ("request_changes", {"questions": []}),
                ("request_changes", {"questions": [" "]}),
                ("complete_review", {"conclusion": " "}),
            ]:
                await send(reviewer, task, action, command(2, **payload), 422)
            old = (await start(legacy))["task_id"]
            assert (await reviewer.get(f"/tasks/{old}")).status_code == 404
            assert (await legacy.get(f"/tasks/{old}")).status_code == 200
            assert (await legacy.get(f"/collaboration/applications/{old}")).status_code == 404
            assert (await legacy.get("/collaboration/notifications")).status_code == 404
            anonymous = httpx.AsyncClient(transport=applicant._transport, base_url="http://test")
            async with anonymous:
                assert (await anonymous.get(path)).status_code == 401

    run(scenario())


def test_info_and_unconnected_role_events_fail_closed(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            for client, role in zip(sessions[:2], ("applicant", "safety_manager")):
                info = (await client.get("/console/api/info")).json()
                assert info["collaboration_role"] == role
                assert info["capabilities"]["create_application"] == (role == "applicant")
                assert info["capabilities"]["run_event_review"] is False
                assert info["simulation_enabled"] is False
                for method, path, body in [
                    ("post", "/sources/any/events", {}),
                    ("post", "/events/any/process", {}),
                    ("post", "/events/any/reviews", {"request_id": "no"}),
                    (
                        "post",
                        "/reviews/any/feedback",
                        {"request_id": "no", "expected_revision": 1, "decision": "confirmed"},
                    ),
                    ("post", "/reviews/any/recover", {}),
                    (
                        "post",
                        "/console/api/tasks/any/events",
                        {"request_id": "no", "expected_revision": 1, "kind": "helmet_missing"},
                    ),
                ]:
                    assert (await client.request(method, path, json=body)).status_code == 404

    run(scenario())
