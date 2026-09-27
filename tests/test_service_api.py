import asyncio
from uuid import uuid4

import httpx
import pytest
from test_events import NOW, OWNER, payload
from test_events_postgres import dsn, run, setup  # noqa: F401 -- real PG fixture
from test_material_revisions import COMPLETE, PATCH
from test_perception_postgres import REFS

from anlan.knowledge.tool import UnavailableKnowledgeStore

TOKEN = "a" * 64
OTHER_TOKEN = "b" * 64


async def configured(dsn):  # noqa: F811
    from anlan.interfaces.api import create_app
    from anlan.interfaces.service_config import ServiceConfig

    _, state, binding = await setup(dsn)
    config = ServiceConfig.model_validate(
        {
            "schema_version": "local-service-v1",
            "as_of": NOW.isoformat(),
            "tokens": [
                {"token": TOKEN, "identity": OWNER.model_dump()},
                {"token": OTHER_TOKEN, "identity": OWNER.model_dump() | {"user_id": "other"}},
            ],
            "sources": [{"binding": binding.model_dump(mode="json"), "references": REFS}],
        }
    )
    return create_app(dsn, config, knowledge=UnavailableKnowledgeStore(lambda: NOW)), state, binding


@pytest.mark.postgres
def test_trusted_identity_precedes_reads_and_request_errors_hide_input(dsn):  # noqa: F811
    async def scenario():
        app, state, _ = await configured(dsn)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (await client.get("/healthz")).status_code == 200
            path = "/tasks/" + state["task_id"]
            for header in [None, "Bearer unknown", "Bearer 注入"]:
                if header == "Bearer 注入":
                    continue  # HTTPX refuses non-ASCII headers at its own boundary.
                response = await client.get(
                    path, headers={"Authorization": header} if header else {}
                )
                assert response.status_code == 401
            assert (
                await client.get(path, headers={"Authorization": "Bearer " + OTHER_TOKEN})
            ).status_code == 404
            headers = {"Authorization": "Bearer " + TOKEN}
            response = await client.post(
                "/tasks",
                headers=headers,
                json={"request_id": "bad", "fields": COMPLETE, "tenant_id": "secret-sentinel"},
            )
            assert response.status_code == 422 and "secret-sentinel" not in response.text
            response = await client.post("/tasks", headers=headers, content=b"x" * 32769)
            assert response.status_code == 413 and "postgresql" not in response.text

    run(scenario())


@pytest.mark.postgres
def test_material_http_idempotency_revise_and_recovery(dsn):  # noqa: F811
    async def scenario():
        app, _, _ = await configured(dsn)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": "Bearer " + TOKEN},
            ) as client,
        ):
            request_id = uuid4().hex
            body = {"request_id": request_id, "fields": COMPLETE}
            initial = await client.post("/tasks", json=body)
            assert initial.status_code == 200
            assert (await client.post("/tasks", json=body)).json() == initial.json()
            task = initial.json()["task_id"]
            assert (await client.get("/tasks/by-request/" + request_id)).json()["task_id"] == task
            revised = await client.post(
                f"/tasks/{task}/revise",
                json={"request_id": "change", "expected_revision": 1, "fields": PATCH},
            )
            assert revised.status_code == 200 and revised.json()["revision"] == 2
            assert (await client.post(f"/tasks/{task}/recover")).json() == revised.json()
            assert len((await client.get(f"/tasks/{task}/history")).json()) == 2

    run(scenario())


@pytest.mark.postgres
def test_event_review_feedback_http_chain_uses_host_source_scope(dsn):  # noqa: F811
    async def scenario():
        app, _, source = await configured(dsn)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": "Bearer " + TOKEN},
            ) as client,
        ):
            received = await client.post(f"/sources/{source.source_id}/events", json=payload())
            assert received.status_code == 200
            receipt = received.json()["receipt_id"]
            review = await client.post(f"/events/{receipt}/reviews", json={"request_id": "api"})
            assert review.status_code == 200 and review.json()["result"]["status"] == "completed"
            review_id = review.json()["review_id"]
            denied = await client.post(
                f"/reviews/{review_id}/feedback",
                json={"request_id": "bad", "expected_revision": 1, "decision": "approve_work"},
            )
            assert denied.status_code == 422
            feedback = await client.post(
                f"/reviews/{review_id}/feedback",
                json={
                    "request_id": "feedback",
                    "expected_revision": 1,
                    "decision": "needs_verification",
                },
            )
            assert feedback.status_code == 200 and feedback.json()["revision"] == 2
            assert (await client.post(f"/reviews/{review_id}/cancel")).json()["result"][
                "status"
            ] == ("completed")
            assert (await client.get(f"/events/{receipt}")).json()["raw"]["alarm_state"] == "active"
            assert (
                await client.post(
                    f"/events/{receipt}/reviews",
                    json={"request_id": "bad-refs", "references": REFS},
                )
            ).status_code == 422

    run(scenario())


def test_snapshot_stream_reconnect_skips_seen_snapshot_and_emits_changed_state():
    from anlan.interfaces.streams import snapshot_id, snapshot_stream

    async def scenario():
        state = {"task_id": "task", "revision": 1}
        reads = 0

        async def read():
            nonlocal reads
            reads += 1
            return state | {"revision": 2}

        async def disconnected():
            return False

        stream = snapshot_stream(state, read, snapshot_id(state), disconnected, poll_seconds=0.01)
        message = await anext(stream)
        assert '"revision": 2' in message and snapshot_id(state) not in message
        assert reads == 1
        await stream.aclose()

    asyncio.run(scenario())
