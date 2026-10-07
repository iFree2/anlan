"""Console exercises actual PG and the existing workflow/feedback authority."""
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from test_events import NOW, OWNER
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import COMPLETE
from test_perception_postgres import REFS

from anlan.common.errors import InvalidTransition
from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig
from anlan.knowledge.tool import UnavailableKnowledgeStore

TOKEN = "c" * 64
OTHER_TOKEN = "d" * 64


def config(enabled=True):
    data = {
        "schema_version": "local-service-v1", "as_of": NOW.isoformat(),
        "tokens": [
            {"token": TOKEN, "identity": OWNER.model_dump()},
            {"token": OTHER_TOKEN, "identity": OWNER.model_dump() | {"user_id": "other"}},
        ],
    }
    if enabled:
        data["console_profiles"] = [{"identity": OWNER.model_dump(), "references": REFS}]
    return ServiceConfig.model_validate(data)


@pytest.mark.postgres
def test_console_static_and_auth_boundary(dsn):  # noqa: F811
    async def scenario():
        app = create_app(dsn, config(), knowledge=UnavailableKnowledgeStore(lambda: NOW))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            shell = await client.get("/console")
            assert shell.status_code == 200 and "安澜" in shell.text
            assert "script-src 'self'" in shell.headers["content-security-policy"]
            assert TOKEN not in shell.text
            assert (await client.get("/console/assets/app.js")).status_code == 200
            assert (await client.get("/console/assets/secret.txt")).status_code == 404
            assert (await client.get("/console/api/tasks")).status_code == 401
            headers = {"Authorization": "Bearer " + TOKEN}
            info = (await client.get("/console/api/info", headers=headers)).json()
            assert info["model_mode"] == "scripted_double"
            assert info["identity"] == OWNER.model_dump()
            assert TOKEN not in str(info)
    run(scenario())


def test_console_assets_follow_trusted_reverse_proxy_prefix():
    async def scenario():
        app = create_app("unused", config(False), root_path="/anlan")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            page = await client.get("/console")
            assert page.status_code == 200
            assert 'src="/anlan/console/assets/app.js"' in page.text
            assert 'href="/anlan/console/assets/styles.css"' in page.text
        with pytest.raises(ValueError):
            create_app("unused", config(False), root_path='"/unsafe')
    run(scenario())


@pytest.mark.postgres
@pytest.mark.parametrize("kind", ["helmet_missing", "gas_abnormal"])
def test_console_workflow_events_feedback_revision_and_isolation(dsn, kind):  # noqa: F811
    async def scenario():
        cfg = config()
        app = create_app(dsn, cfg, knowledge=UnavailableKnowledgeStore(lambda: NOW))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            fields = COMPLETE | {"work_method_description": ""}
            task = (await client.post("/tasks", json={
                "request_id": uuid4().hex, "fields": fields,
            })).json()
            task_id = task["task_id"]
            assert task["status"] == "waiting_input"
            task = (await client.post(f"/tasks/{task_id}/resume", json={
                "request_id": uuid4().hex, "expected_revision": 1,
                "fields": {"work_method_description": "SYNTHETIC：焊接试件"},
            })).json()
            assert task["revision"] == 2 and task["status"] == "awaiting_review"
            assert task_id in [t["task_id"] for t in (
                await client.get("/console/api/tasks")
            ).json()["items"]]
            path = f"/console/api/tasks/{task_id}/events"
            body = {"request_id": uuid4().hex, "expected_revision": 2, "kind": kind}
            bad = await client.post(path, json=body | {"tenant_id": "fake"})
            assert bad.status_code == 422
            stale = await client.post(path, json=body | {"expected_revision": 1})
            assert stale.status_code == 409
            received = await client.post(path, json=body)
            assert received.status_code == 200
            event = received.json()
            assert event["binding"]["task_id"] == task_id
            assert event["binding"]["identity"] == OWNER.model_dump()
            assert event["raw"]["alarm_state"] == "active"
            assert (await client.post(path, json=body)).json()["receipt_id"] == event["receipt_id"]
            changed_kind = "gas_abnormal" if kind == "helmet_missing" else "helmet_missing"
            assert (await client.post(path, json=body | {"kind": changed_kind})).status_code == 409
            assert len((await client.get(path)).json()["items"]) == 1
            receipt = event["receipt_id"]
            reviewed = await client.post(f"/console/api/events/{receipt}/reviews", json={
                "request_id": uuid4().hex,
            })
            assert reviewed.status_code == 200
            review = reviewed.json()
            assert review["result"]["status"] == "completed"
            assert review["result"]["report"]["mode"] == "scripted_double"
            rid = review["review_id"]
            feedback = {"request_id": uuid4().hex, "expected_revision": 1,
                        "decision": "needs_verification"}
            assert (await client.post(f"/reviews/{rid}/feedback", json=feedback)).status_code == 200
            assert (await client.get(f"/console/api/events/{receipt}/reviews")).json()["items"]
            assert (await client.post(f"/tasks/{task_id}/revise", json={
                "request_id": uuid4().hex, "expected_revision": 2,
                "fields": {"work_location_description": "SYNTHETIC：修改后的台架"},
            })).status_code == 200
            assert (await client.get(f"/reviews/{rid}")).json()["currentness"] == "stale_material"
            assert (await client.post(f"/reviews/{rid}/feedback", json=feedback | {
                "request_id": uuid4().hex, "expected_revision": 2,
            })).status_code == 409
            assert (await client.get(f"/events/{receipt}")).json()["raw"]["alarm_state"] == "active"
            other = {"Authorization": "Bearer " + OTHER_TOKEN}
            assert (await client.get(path, headers=other)).status_code == 404
            assert (await client.post(path, headers=other, json=body)).status_code == 404
            assert (await client.get(f"/console/api/events/{receipt}/reviews", headers=other)
                    ).status_code == 404
            assert task_id not in [t["task_id"] for t in (
                await client.get("/console/api/tasks", headers=other)
            ).json()["items"]]
        # New app/config instance must read the durable records without in-memory bindings.
        app2 = create_app(dsn, cfg, knowledge=UnavailableKnowledgeStore(lambda: NOW))
        async with app2.router.lifespan_context(app2), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app2), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            assert len((await client.get(path)).json()["items"]) == 1
            assert (await client.get(f"/reviews/{rid}")).json()["feedback"] is not None
    run(scenario())


@pytest.mark.postgres
def test_console_simulation_is_disabled_without_trusted_profile(dsn):  # noqa: F811
    async def scenario():
        app = create_app(dsn, config(False), knowledge=UnavailableKnowledgeStore(lambda: NOW))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            task = (await client.post("/tasks", json={
                "request_id": uuid4().hex, "fields": COMPLETE,
            })).json()
            assert (await client.get("/console/api/info")).json()["simulation_enabled"] is False
            assert (await client.post(f"/console/api/tasks/{task['task_id']}/events", json={
                "request_id": uuid4().hex, "kind": "helmet_missing", "expected_revision": 1,
            })).status_code == 404
    run(scenario())


@pytest.mark.postgres
def test_console_pending_first_checkpoint_can_recover(dsn):  # noqa: F811
    async def scenario():
        app = create_app(dsn, config(), knowledge=UnavailableKnowledgeStore(lambda: NOW))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            with patch("anlan.workflows.service.WorkflowService._execute",
                       side_effect=InvalidTransition("synthetic first checkpoint interruption")):
                failed = await client.post("/tasks", json={
                    "request_id": uuid4().hex, "fields": COMPLETE,
                })
            assert failed.status_code == 409
            task_id = failed.json()["task_id"]
            assert (await client.get("/tasks/" + task_id)).status_code == 409
            assert task_id in [t["task_id"] for t in (
                await client.get("/console/api/tasks")
            ).json()["items"]]
            recovered = await client.post(f"/tasks/{task_id}/recover")
            assert recovered.status_code == 200
            assert recovered.json()["status"] == "awaiting_review"
    run(scenario())


@pytest.mark.postgres
def test_console_order_is_independent_of_fixed_business_clock(dsn):  # noqa: F811
    async def scenario():
        app = create_app(dsn, config(), knowledge=UnavailableKnowledgeStore(lambda: NOW))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            task = (await client.post("/tasks", json={
                "request_id": uuid4().hex, "fields": COMPLETE,
            })).json()
            path = f"/console/api/tasks/{task['task_id']}/events"
            events = [(await client.post(path, json={
                "request_id": uuid4().hex, "expected_revision": 1, "kind": "helmet_missing",
            })).json() for _ in range(2)]
            assert events[0]["received_at"] == events[1]["received_at"]
            listed = (await client.get(path)).json()["items"]
            assert [e["receipt_id"] for e in listed] == [
                events[1]["receipt_id"], events[0]["receipt_id"],
            ]
            rid = events[1]["receipt_id"]
            reviews = [(await client.post(f"/console/api/events/{rid}/reviews", json={
                "request_id": uuid4().hex,
            })).json() for _ in range(2)]
            assert reviews[0]["created_at"] == reviews[1]["created_at"]
            listed = (await client.get(f"/console/api/events/{rid}/reviews")).json()["items"]
            assert [r["review_id"] for r in listed] == [
                reviews[1]["review_id"], reviews[0]["review_id"],
            ]
    run(scenario())
