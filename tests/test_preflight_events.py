"""B3 events use the confirmed application binding, never a console profile's facts."""

from uuid import uuid4

from test_collaboration_api import clients, command, send, settings, start
from test_events_postgres import dsn, run  # noqa: F401
from test_perception_postgres import REFS
from test_preflight_contracts import command as binding_command

from anlan.interfaces.service_config import ServiceConfig
from anlan.preflight.bindings import BindingService


def configured():
    config, actors, tokens = settings()
    # This profile grants simulated-event capability only. Its legacy references must not
    # become the task's worker/area selection.
    return ServiceConfig.model_validate(config.model_dump() | {"console_profiles": [
        {"identity": actors[1].model_dump(), "references": REFS}
    ]}), actors, tokens


def test_console_events_follow_confirmed_binding_and_old_review_is_stale_binding(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn, configured()) as (sessions, actors, config):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            first = (await reviewer.post(f"/console/api/tasks/{task}/events", json={
                "request_id": uuid4().hex, "expected_revision": 1, "kind": "helmet_missing",
            })).json()
            assert first["binding"]["object_ref"] == "area-a"
            assert first["binding"]["binding_revision"] == 1
            review = await reviewer.post(f"/console/api/events/{first['receipt_id']}/reviews",
                                         json={"request_id": "first-review"})
            assert review.status_code == 200, review.text

            await send(reviewer, task, "request_changes", command(2, questions=["换作业区域"]))
            await BindingService(
                reviewer._transport.app.state.preflight.store.dsn, config,
                reviewer._transport.app.state.preflight.service_context_factory,
            ).confirm(actors[0], task, binding_command(
                request_id="bind-new-area", expected_binding_revision=1,
                worker_id="worker-b", area_id="area-b",
            ))
            assert (await reviewer.get(f"/reviews/{review.json()['review_id']}")).json()[
                "currentness"] == "stale_binding"
            assert (await applicant.get(f"/events/{first['receipt_id']}")).json()["raw"][
                "alarm_state"] == "active"

            await send(applicant, task, "resubmit", command(
                3, 1, reply="已确认新对象", expected_binding_revision=2
            ))
            second = await reviewer.post(f"/console/api/tasks/{task}/events", json={
                "request_id": uuid4().hex, "expected_revision": 1, "kind": "gas_abnormal",
            })
            assert second.status_code == 200, second.text
            assert second.json()["binding"]["object_ref"] == "area-b"
            assert second.json()["binding"]["binding_revision"] == 2
    run(scenario())


def test_upgraded_shared_receipt_without_binding_revision_is_not_private_legacy(dsn):  # noqa: F811
    """P12 receipts are readable history but cannot remain current after the P13 upgrade."""
    async def scenario():
        async with clients(dsn, configured()) as (sessions, actors, config):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            event = (await reviewer.post(f"/console/api/tasks/{task}/events", json={
                "request_id": uuid4().hex, "expected_revision": 1, "kind": "helmet_missing",
            })).json()
            review = await reviewer.post(f"/console/api/events/{event['receipt_id']}/reviews",
                                         json={"request_id": "old-shared"})
            assert review.status_code == 200
            async with reviewer._transport.app.state.preflight.store.connection() as conn:
                await conn.execute(
                    "UPDATE anlan_v2.perception_events SET document=jsonb_set("
                    "document,'{binding}',(document->'binding')-'binding_revision') "
                    "WHERE receipt_id=%s",
                    (event["receipt_id"],),
                )
            await send(reviewer, task, "request_changes", command(2, questions=["换绑定"]))
            await BindingService(
                reviewer._transport.app.state.preflight.store.dsn, config,
                reviewer._transport.app.state.preflight.service_context_factory,
            ).confirm(actors[0], task, binding_command(
                request_id="upgrade-bind", expected_binding_revision=1,
                worker_id="worker-b", area_id="area-b",
            ))
            view = (await reviewer.get(f"/reviews/{review.json()['review_id']}")).json()
            assert view["currentness"] == "stale_binding"
            assert (await applicant.get(f"/events/{event['receipt_id']}")).json()["raw"][
                "alarm_state"] == "active"
    run(scenario())
