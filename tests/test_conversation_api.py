from uuid import uuid4

import httpx
import pytest
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401
from test_service_api import OTHER_TOKEN, TOKEN, configured

from anlan.infrastructure.conversations import ConversationStore

pytestmark = pytest.mark.postgres


async def create(client, request_id=None):
    return await client.post(
        "/conversations", json={"request_id": request_id or uuid4().hex}
    )


def test_conversation_api_authentication_idempotency_list_and_tenant_isolation(dsn):  # noqa: F811
    async def scenario():
        app, _, _ = await configured(dsn)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (await create(client)).status_code == 401
            headers = {"Authorization": "Bearer " + TOKEN}
            request_id = uuid4().hex
            first = await client.post(
                "/conversations", headers=headers, json={"request_id": request_id}
            )
            assert first.status_code == 200
            replay = await client.post(
                "/conversations", headers=headers, json={"request_id": request_id}
            )
            assert replay.json() == first.json()
            conversation_id = first.json()["conversation_id"]
            listed = await client.get("/conversations", headers=headers)
            assert conversation_id in {
                item["conversation_id"] for item in listed.json()
            }
            assert (
                await client.get(
                    f"/conversations/{conversation_id}",
                    headers={"Authorization": "Bearer " + OTHER_TOKEN},
                )
            ).status_code == 404

    run(scenario())


def test_candidate_confirmation_and_replay_return_one_task_projection(dsn):  # noqa: F811
    async def scenario():
        app, _, _ = await configured(dsn)
        headers = {"Authorization": "Bearer " + TOKEN}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers,
            ) as client,
        ):
            conversation = (await create(client)).json()
            path = f"/conversations/{conversation['conversation_id']}/messages"
            candidate_body = {
                "request_id": "message-1",
                "expected_revision": 1,
                "text": "明天在一号罐区 V101 管线上补焊",
            }
            candidate = await client.post(path, json=candidate_body)
            assert candidate.status_code == 200
            assert candidate.json()["status"] == "pending_confirmation"
            assert candidate.json()["task_projection"] is None
            assert (await client.post(path, json=candidate_body)).json() == candidate.json()
            confirmation_body = {
                "request_id": "message-2",
                "expected_revision": candidate.json()["revision"],
                "text": "确认申请",
            }
            confirmed = await client.post(path, json=confirmation_body)
            assert confirmed.status_code == 200
            assert confirmed.json()["status"] == "active_hot_work"
            assert confirmed.json()["task_projection"]["task_id"]
            assert (await client.post(path, json=confirmation_body)).json() == confirmed.json()

    run(scenario())


def test_conversation_api_validation_conflicts_and_stream_cursor(dsn):  # noqa: F811
    async def scenario():
        app, _, _ = await configured(dsn)
        headers = {"Authorization": "Bearer " + TOKEN}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers,
            ) as client,
        ):
            assert (
                await client.post(
                    "/conversations", json={"request_id": "valid", "tenant_id": "secret"}
                )
            ).status_code == 422
            assert (await client.post("/conversations", content=b"x" * 32769)).status_code == 413
            conversation = (await create(client)).json()
            path = f"/conversations/{conversation['conversation_id']}/messages"
            oversized = await client.post(
                path,
                json={"request_id": "large", "expected_revision": 1, "text": "x" * 8193},
            )
            assert oversized.status_code == 422
            first = await client.post(
                path,
                json={"request_id": "first", "expected_revision": 1, "text": "你好"},
            )
            assert first.status_code == 200
            stale = await client.post(
                path,
                json={"request_id": "stale", "expected_revision": 1, "text": "你好"},
            )
            assert stale.status_code == 409
            pending = await ConversationStore(dsn).reserve_message(
                OWNER,
                conversation["conversation_id"],
                "pending",
                first.json()["revision"],
                "处理中",
            )
            assert pending["status"] == "pending"
            busy = await client.post(
                path,
                json={
                    "request_id": "busy",
                    "expected_revision": first.json()["revision"] + 1,
                    "text": "第二条",
                },
            )
            assert busy.status_code == 409
            invalid_cursor = await client.get(
                f"/conversations/{conversation['conversation_id']}/stream",
                headers={"Last-Event-ID": "invalid"},
            )
            assert invalid_cursor.status_code == 422

    run(scenario())
