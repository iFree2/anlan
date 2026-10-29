"""B3 HTTP boundaries expose only server-derived preflight state."""

from uuid import uuid4

from test_collaboration_api import clients, command, send, start
from test_events_postgres import dsn, run  # noqa: F401
from test_preflight_contracts import command as binding_command


def test_preflight_routes_are_authenticated_versioned_and_role_bound(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer, outsider = sessions[:3]
            task = (await start(applicant))["task_id"]
            base = f"/collaboration/applications/{task}"

            catalog = await applicant.get(base + "/object-catalog")
            assert catalog.status_code == 200, catalog.text
            assert catalog.json()["workers"] and catalog.json()["areas"]
            assert (await outsider.get(base + "/object-catalog")).status_code == 404

            binding = await applicant.get(base + "/binding")
            assert binding.status_code == 200 and binding.json()["binding_revision"] == 1
            duplicate = await applicant.post(base + "/binding", json=binding_command(
                request_id="http-binding-" + uuid4().hex, expected_binding_revision=1
            ))
            assert duplicate.status_code == 200 and duplicate.json()["binding_revision"] == 1
            assert (await applicant.post(base + "/binding", json=binding_command(
                request_id="forged", expected_binding_revision=1
            ) | {"actor": {"user_id": "reviewer"}})).status_code == 422

            before = await applicant.get(base + "/prechecks")
            assert before.status_code == 200 and before.json()["status"] == "not_checked"
            assert before.json()["binding"]["labels"] == {
                "worker": "合成人员a",
                "qualification": "合成焊接资质",
                "area": "合成区域a",
            }
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            queued = await reviewer.get(base + "/prechecks")
            assert queued.status_code == 200 and queued.json()["status"] in {"queued", "running"}
            body = {
                "request_id": "http-recheck-" + uuid4().hex,
                "expected_material_revision": 1,
                "expected_binding_revision": 1,
                "expected_application_version": 2,
                "reason": "SYNTHETIC：资料维护后人工重新核对",
            }
            recheck = await reviewer.post(base + "/prechecks", json=body)
            assert recheck.status_code == 200 and recheck.json()["job_id"]
            forged = await reviewer.post(base + "/prechecks", json=body | {"ready": True})
            assert forged.status_code == 422
            assert (await outsider.post(base + "/prechecks", json=body)).status_code == 404
    run(scenario())
