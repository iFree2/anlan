"""Live console composition uses real PG and a controlled provider transport."""
import json
from uuid import uuid4

import httpx
import pytest
from test_console import OTHER_TOKEN, TOKEN, config
from test_events import NOW
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import COMPLETE

from anlan.infrastructure.budget import BudgetLedger
from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig
from anlan.knowledge.tool import UnavailableKnowledgeStore
from anlan.llm.config import ModelConfig
from anlan.llm.perception import ScriptedPerceptionModel


def live_config():
    return ServiceConfig.model_validate(config().model_dump() | {"model_mode": "deepseek_live"})


def test_live_mode_requires_server_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        create_app("unused", live_config())


@pytest.mark.postgres
def test_live_material_and_event_share_budget_and_keep_history(dsn):  # noqa: F811
    async def scenario():
        ledger = BudgetLedger(dsn, "test-" + uuid4().hex)
        await ledger.initialize()
        sent = []

        async def provider(request):
            payload = json.loads(request.content)
            budget = await ledger.snapshot()
            assert budget["total_reserved"] == len(sent) + 1
            assert budget["attempts"][-1]["work_package"] == "P8-WP03"
            assert request.url.host == "api.deepseek.com"
            sent.append(payload)
            if "event" in json.loads(payload["messages"][1]["content"]):
                generated = await ScriptedPerceptionModel().generate(payload, "test")
                output = generated["candidate"]
            else:
                output = {"issues": []}
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {
                    "role": "assistant", "content": json.dumps(output)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            })

        knowledge = UnavailableKnowledgeStore(lambda: NOW)
        old_app = create_app(dsn, config(), knowledge=knowledge)
        async with old_app.router.lifespan_context(old_app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=old_app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            old = (await client.post("/tasks", json={
                "request_id": uuid4().hex, "fields": COMPLETE})).json()
            old_event = (await client.post(
                "/console/api/tasks/" + old["task_id"] + "/events", json={
                    "request_id": uuid4().hex, "expected_revision": 1,
                    "kind": "helmet_missing"})).json()
        app = create_app(dsn, live_config(), knowledge=knowledge,
                         model_config=ModelConfig(api_key="provider-secret"),
                         model_transport=httpx.MockTransport(provider), budget_ledger=ledger)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            info = (await client.get("/console/api/info")).json()
            assert info["material_mode"] == info["model_mode"] == "deepseek_live"
            assert info["budget"]["package_remaining"] == 10
            assert "provider-secret" not in json.dumps(info)
            payload = {"request_id": uuid4().hex, "fields": COMPLETE}
            created = await client.post("/tasks", json=payload)
            assert created.status_code == 200
            task = created.json()
            assert task["analysis_mode"] == "deepseek_live"
            assert task["analysis"]["semantic_status"] == "checked"
            assert task["analysis"]["model"] == "deepseek-flash"
            assert (await client.post("/tasks", json=payload)).json() == task
            assert len(sent) == 1
            items = (await client.get("/console/api/tasks")).json()["items"]
            assert {old["task_id"], task["task_id"]} <= {i["task_id"] for i in items}
            assert (await client.get("/tasks/" + old["task_id"])).json() == old
            assert (await client.post("/tasks/" + old["task_id"] + "/revise", json={
                "request_id": uuid4().hex, "expected_revision": 1,
                "fields": {"work_method_description": "SYNTHETIC revised"},
            })).status_code == 409
            assert (await client.post("/console/api/tasks/" + old["task_id"] + "/events",
                                      json={"request_id": uuid4().hex,
                                            "expected_revision": 1,
                                            "kind": "gas_abnormal"})).status_code == 409
            assert (await client.post(
                "/console/api/events/" + old_event["receipt_id"] + "/reviews",
                json={"request_id": uuid4().hex})).status_code == 409
            assert len(sent) == 1
            assert (await client.get("/tasks/" + task["task_id"], headers={
                "Authorization": "Bearer " + OTHER_TOKEN})).status_code == 404
            event = await client.post("/console/api/tasks/" + task["task_id"] + "/events",
                                      json={"request_id": uuid4().hex,
                                            "expected_revision": 1, "kind": "helmet_missing"})
            assert event.status_code == 200
            url = "/console/api/events/" + event.json()["receipt_id"] + "/reviews"
            request = {"request_id": uuid4().hex}
            review = await client.post(url, json=request)
            assert review.status_code == 200
            report = review.json()["result"]["report"]
            assert report["mode"] == "deepseek_live"
            assert report["work_package"] == "P8-WP03"
            assert report["stop_reason"] == "completed"
            assert report["attempt_id"] and report["usage"]["total_tokens"] == 20
            replay = (await client.post(url, json=request)).json()
            assert replay["review_id"] == review.json()["review_id"]
            assert len(sent) == 2
            budget = await ledger.snapshot()
            assert budget["packages"] == {"P8-WP03": 2}
            assert budget["status_counts"] == {"reserved": 0, "succeeded": 2, "failed": 0}
    run(scenario())


@pytest.mark.postgres
def test_live_failure_and_exhaustion_never_fall_back(dsn):  # noqa: F811
    async def scenario():
        ledger = BudgetLedger(dsn, "test-" + uuid4().hex, total_limit=1, package_limit=1)
        await ledger.initialize()
        sent = []

        def provider(request):
            sent.append(True)
            return httpx.Response(401, text="provider-secret must stay hidden")

        app = create_app(dsn, live_config(), knowledge=UnavailableKnowledgeStore(lambda: NOW),
                         model_config=ModelConfig(api_key="provider-secret"),
                         model_transport=httpx.MockTransport(provider), budget_ledger=ledger)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            for category in ["model_unauthorized", "budget_exceeded"]:
                r = await client.post("/tasks", json={
                    "request_id": uuid4().hex, "fields": COMPLETE})
                assert r.status_code == 200
                assert r.json()["analysis"]["error"] == category
                assert r.json()["analysis"]["semantic_status"] != "checked"
                assert "provider-secret" not in r.text
            assert len(sent) == 1
            assert (await ledger.snapshot())["status_counts"]["failed"] == 1
    run(scenario())
