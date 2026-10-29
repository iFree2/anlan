"""Human citation choices are structured, frozen, and never inferred from chat."""

from uuid import uuid4

from test_collaboration_api import clients, command, send, start
from test_collaboration_conversation import bind, conversation, say
from test_events_postgres import dsn, run  # noqa: F401

from anlan.common.models import Identity
from anlan.interfaces.collaboration_conversation import CollaborationConversationAdapter


async def test_replay_of_queued_preflight_remains_idempotent_after_evidence_exists():
    """A queued response has no evidence to protect when its first check completes."""

    class Workflow:
        async def read(self, actor, task_id):
            return None

    class Service:
        async def get(self, actor, task_id):
            return {
                "precheck": {
                    "binding": {"references": {"worker_id": "worker-a"}},
                    "binding_revision": 1,
                    "check_id": "check-done",
                    "evidence": {"citation_ids": ["citation-a"]},
                }
            }

    adapter = CollaborationConversationAdapter(Service(), Workflow())
    cached = {
        "active_task_id": "task-a",
        "task_projection": {
            "collaboration": {
                "precheck": {
                    "binding": {"references": {"worker_id": "worker-a"}},
                    "binding_revision": 1,
                    "check_id": None,
                    "evidence": None,
                }
            }
        },
        "business_messages": [],
    }
    await adapter.validate_cached(
        Identity(tenant_id="tenant-a", user_id="applicant"), cached
    )


def test_human_citation_candidate_freezes_real_ids_and_rejects_stale_card(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer, outsider = sessions[:3]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            app = reviewer._transport.app
            import asyncio

            for _ in range(100):
                evidence = await app.state.preflight.store.latest(
                    app.state.preflight.config.tokens[0].identity.tenant_id, task
                )
                if evidence and evidence["result"] is not None:
                    break
                if evidence:
                    await app.state.preflight.process_next(evidence["job_id"])
                await asyncio.sleep(0.01)
            assert evidence and evidence["result"] is not None
            citations = evidence["result"]["citation_ids"]
            versions = ("material_revision", "binding_revision", "application_version")
            assert citations, repr(evidence["result"] | {"job": {
                key: evidence[key] for key in versions
            }})
            review_conversation = await bind(reviewer, await conversation(reviewer), task)
            path = (
                f"/conversations/{review_conversation['conversation_id']}"
                "/preflight-citation-candidates"
            )
            body = {
                "request_id": "human-citation-" + uuid4().hex,
                "expected_revision": review_conversation["revision"],
                "expected_check_id": evidence["check_id"],
                "expected_material_revision": 1,
                "expected_binding_revision": 1,
                "expected_application_version": 2,
                "conclusion": "已人工核对本轮实际适用引用",
                "applied_knowledge_citation_ids": citations,
            }
            created = await reviewer.post(path, json=body)
            assert created.status_code == 200, created.text
            frozen = created.json()["pending_intent"]["collaboration"]["payload"]
            assert frozen["applied_knowledge_citation_ids"] == citations
            assert frozen["expected_binding_revision"] == 1
            assert frozen["expected_check_id"] == evidence["check_id"]
            assert (await outsider.post(path, json=body)).status_code == 404

            recheck = await reviewer.post(f"/collaboration/applications/{task}/prechecks", json={
                "request_id": "invalidate-card", "expected_material_revision": 1,
                "expected_binding_revision": 1, "expected_application_version": 2,
                "reason": "SYNTHETIC：新轮人工复核",
            })
            assert recheck.status_code == 200
            await say(reviewer, created.json(), "确认", status=409)
            stale = (await reviewer.get(
                f"/conversations/{review_conversation['conversation_id']}"
            )).json()
            assert stale["pending_intent"]["collaboration"]["payload"] == frozen
            for _ in range(100):
                replacement = await app.state.preflight.store.latest(
                    app.state.preflight.config.tokens[0].identity.tenant_id, task
                )
                if replacement and replacement["result"] is not None:
                    break
                if replacement:
                    await app.state.preflight.process_next(replacement["job_id"])
                await asyncio.sleep(0.01)
            assert replacement and replacement["result"] is not None
            assert replacement["result"]["citation_ids"]
            current = (await reviewer.get(f"/collaboration/applications/{task}")).json()
            fresh = await reviewer.post(path, json=body | {
                "request_id": "human-citation-fresh", "expected_revision": stale["revision"],
                "expected_check_id": current["precheck"]["check_id"],
                "expected_material_revision": current["materials"]["revision"],
                "expected_binding_revision": current["precheck"]["binding_revision"],
                "expected_application_version": current["application"]["version"],
                "applied_knowledge_citation_ids": replacement["result"]["citation_ids"],
            })
            assert fresh.status_code == 200, fresh.text
            completed = await say(reviewer, fresh.json(), "确认")
            assert completed["task_projection"]["collaboration"]["application"]["status"] == (
                "review_completed"
            )
    run(scenario())


def test_human_citation_choice_rejects_check_replaced_before_card_creation(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            app = reviewer._transport.app
            for _ in range(100):
                before = await app.state.preflight.store.latest(
                    app.state.preflight.config.tokens[0].identity.tenant_id, task
                )
                if before and before["result"] is not None:
                    break
                if before:
                    await app.state.preflight.process_next(before["job_id"])
            assert before and before["result"] and before["result"]["citation_ids"]
            conv = await bind(reviewer, await conversation(reviewer), task)
            snapshot = (await reviewer.get(f"/collaboration/applications/{task}")).json()
            assert snapshot["precheck"]["check_id"] == before["check_id"]
            assert (await reviewer.post(f"/collaboration/applications/{task}/prechecks", json={
                "request_id": "replace-before-card", "expected_material_revision": 1,
                "expected_binding_revision": 1, "expected_application_version": 2,
                "reason": "SYNTHETIC：来源更新后重查",
            })).status_code == 200
            stale_choice = {
                "request_id": "stale-human-choice", "expected_revision": conv["revision"],
                "expected_check_id": before["check_id"], "expected_material_revision": 1,
                "expected_binding_revision": 1, "expected_application_version": 2,
                "conclusion": "旧界面勾选不应迁移", 
                "applied_knowledge_citation_ids": before["result"]["citation_ids"],
            }
            response = await reviewer.post(
                f"/conversations/{conv['conversation_id']}/preflight-citation-candidates",
                json=stale_choice,
            )
            assert response.status_code == 409, response.text
    run(scenario())


def test_cached_preflight_batch_is_not_replayed_after_acl_revocation_and_rebind(dsn):  # noqa: F811
    """A current B batch cannot authorize replay of a cached, revoked A batch."""
    async def scenario():
        import json

        from test_preflight_contracts import command as binding_command

        from anlan.preflight.bindings import BindingService

        async with clients(dsn) as (sessions, actors, config):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            app = reviewer._transport.app
            for _ in range(100):
                initial = await app.state.preflight.store.latest(actors[0].tenant_id, task)
                if initial and initial["result"] is not None:
                    break
                if initial:
                    await app.state.preflight.process_next(initial["job_id"])
            assert initial and initial["result"] and initial["result"]["citation_ids"]
            conv = await bind(reviewer, await conversation(reviewer), task)
            message_path = f"/conversations/{conv['conversation_id']}/messages"
            replay = {
                "request_id": "cache-a",
                "expected_revision": conv["revision"],
                "text": "查看依据",
            }
            first = await reviewer.post(message_path, json=replay)
            assert first.status_code == 200 and first.json()["task_projection"]["collaboration"][
                "precheck"]["binding"]["references"]["worker_id"] == "worker-a"

            await send(reviewer, task, "request_changes", command(2, questions=["改用 B 对象"]))
            facts = config.facts_dir / "access.json"
            access = json.loads(facts.read_text(encoding="utf-8"))
            for record in access["records"]:
                if record["user_id"] == actors[1].user_id:
                    record["worker_ids"] = ["worker-b"]
                    record["area_ids"] = ["area-b"]
            facts.write_text(json.dumps(access), encoding="utf-8")
            await BindingService(app.state.preflight.store.dsn, config,
                                 app.state.preflight.service_context_factory).confirm(
                actors[0], task, binding_command(request_id="bind-b", expected_binding_revision=1,
                                                  worker_id="worker-b", area_id="area-b")
            )
            await send(applicant, task, "resubmit", command(
                3, 1, reply="已绑定 B", expected_binding_revision=2
            ))
            for _ in range(100):
                replacement = await app.state.preflight.store.latest(actors[0].tenant_id, task)
                if replacement and replacement["result"] is not None:
                    break
                if replacement:
                    await app.state.preflight.process_next(replacement["job_id"])
            fresh = (await reviewer.get(f"/collaboration/applications/{task}")).json()["precheck"]
            assert replacement and replacement["result"] and fresh["binding"]["references"][
                "worker_id"] == "worker-b"
            assert fresh["evidence"] and fresh["check_id"] == replacement["check_id"]
            # The exact original request is an idempotent read/replay, never a new command.
            assert (await reviewer.post(message_path, json=replay)).status_code == 404
    run(scenario())
