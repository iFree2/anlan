"""Real PG conversation cards preserve private threads and frozen commands."""

from contextlib import AsyncExitStack, asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_collaboration_api import clients, command, send, start
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import PATCH

from anlan.common.errors import TaskBusy
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.postgres import PostgresRegistry
from anlan.llm.conversation import ConversationContext, ScriptedConversationModel, serialize_context
from anlan.workflows.material_analysis import Analysis
from anlan.workflows.material_contracts import Issue

pytestmark = pytest.mark.postgres


async def conversation(client):
    response = await client.post('/conversations', json={'request_id': uuid4().hex})
    assert response.status_code == 200, response.text
    return response.json()


async def bind(client, conv, task, status=200):
    response = await client.post(f"/conversations/{conv['conversation_id']}/task", json={
        'task_id': task, 'expected_revision': conv['revision']})
    assert response.status_code == status, response.text
    return response.json()


async def say(client, conv, text, status=200, request_id=None):
    response = await client.post(f"/conversations/{conv['conversation_id']}/messages", json={
        'request_id': request_id or uuid4().hex, 'expected_revision': conv['revision'],
        'text': text})
    assert response.status_code == status, response.text
    return response.json()


def test_four_cards_confirm_full_round_trip_and_private_messages(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))['task_id']
            a = await bind(applicant, await conversation(applicant), task)
            b = await conversation(reviewer)
            a = await say(applicant, a, '申请人私聊哨兵 PRIVATE-APPLICANT')
            a = await say(applicant, a, '提交申请给 reviewer')
            frozen = a['pending_intent']['collaboration']
            assert frozen['action'] == 'submit' and frozen['task_id'] == task
            assert frozen['payload']['expected_application_version'] == 1
            assert frozen['payload']['expected_material_revision'] == 1
            assert frozen['payload']['reviewer_user_id'] == 'reviewer'
            assert (await applicant.get(f'/collaboration/applications/{task}')).json()[
                'application']['status'] == 'draft'
            args = (applicant, a, '确认')
            a = await say(*args, request_id='confirm-submit')
            assert await say(*args, request_id='confirm-submit') == a
            b = await bind(reviewer, b, task)
            assert b['task_projection']['semantic_status'] == 'shared_materials'
            assert a['conversation_id'] != b['conversation_id']
            assert 'PRIVATE-APPLICANT' not in str(b)
            b = await say(reviewer, b, '安全人员私聊哨兵 PRIVATE-REVIEWER')
            b = await say(reviewer, b, '要求补充：明确作业具体点位')
            assert (await applicant.get('/collaboration/notifications')).json()['items'] == []
            b = await say(reviewer, b, '确认')
            a = (await applicant.get(f"/conversations/{a['conversation_id']}")).json()
            assert '明确作业具体点位' in str(a['business_messages'])
            assert 'PRIVATE-REVIEWER' not in str(a)
            revision = a['task_projection']['revision']
            response = await applicant.post(f'/tasks/{task}/revise', json={
                'request_id': 'patch', 'expected_revision': revision, 'fields': PATCH})
            assert response.status_code == 200
            a = await say(applicant, a, '重新提交申请：已补充具体点位')
            assert a['pending_intent']['collaboration']['payload'][
                'expected_material_revision'] == 2
            a = await say(applicant, a, '确认')
            b = await say(reviewer, b, '完成材料核查：已人工核对本轮材料')
            assert b['pending_intent']['collaboration']['action'] == 'complete_review'
            assert b['pending_intent']['collaboration']['payload'][
                'applied_knowledge_citation_ids'] == []
            # Plain chat has not selected the actual references. It cannot complete P13.
            await say(reviewer, b, '确认', status=409)
            await send(reviewer, task, 'complete_review', command(
                4, 2, conclusion='已通过结构化命令选择本轮实际引用'))
            b = (await reviewer.get(f"/conversations/{b['conversation_id']}")).json()
            assert b['task_projection']['collaboration']['application']['status'] == (
                'review_completed')
            timeline = (await applicant.get(f'/collaboration/applications/{task}')).json()['events']
            assert [e['action'] for e in timeline] == [
                'submit', 'request_changes', 'resubmit', 'complete_review']
            assert (await reviewer.get(f"/conversations/{a['conversation_id']}")).status_code == 404
    run(scenario())


@pytest.mark.parametrize('text', ['不确认', '他说“确认”是什么意思？', '今天天气不错'])
def test_reject_reference_and_chat_do_not_submit(dsn, text):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            actor = sessions[0]
            task = (await start(actor))['task_id']
            conv = await bind(actor, await conversation(actor), task)
            conv = await say(actor, conv, '提交申请给 reviewer')
            result = await say(actor, conv, text)
            assert (result['pending_intent'] is None) == (text == '不确认')
            assert (await actor.get(f'/collaboration/applications/{task}')).json()[
                'application']['version'] == 1
    run(scenario())


def test_stale_card_cannot_replace_frozen_versions_or_reviewer(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))['task_id']
            a = await bind(applicant, await conversation(applicant), task)
            a = await say(applicant, a, '提交申请给 reviewer')
            frozen = a['pending_intent']['collaboration']
            await send(applicant, task, 'submit', command(reviewer_user_id='unassigned'))
            await say(applicant, a, '确认', status=409)
            latest = (await applicant.get(f"/conversations/{a['conversation_id']}")).json()
            assert latest['pending_intent']['collaboration'] == frozen
            assert (await reviewer.get(f'/collaboration/applications/{task}')).status_code == 404
    run(scenario())


def test_shared_binding_rejects_third_party_and_manager_material_candidates(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer, unassigned, other, _, foreign = sessions
            task = (await start(applicant))['task_id']
            await send(applicant, task, 'submit', command(reviewer_user_id='reviewer'))
            for client in (unassigned, other, foreign):
                await bind(client, await conversation(client), task, 404)
            b = await bind(reviewer, await conversation(reviewer), task)
            for text in ('位置在伪造区域', '我要发起另一项动火任务'):
                b = await say(reviewer, b, text)
                assert b['pending_intent'] is None
            assert (await applicant.get(f'/tasks/{task}')).json()['revision'] == 1
    run(scenario())


def test_models_receive_only_own_private_messages_and_safe_shared_context(dsn):  # noqa: F811
    async def scenario():
        contexts = []
        original = ScriptedConversationModel.classify

        async def capture(model, context, **kwargs):
            contexts.append((context.collaboration_role, serialize_context(context)))
            return await original(model, context, **kwargs)

        async with AsyncExitStack() as stack:
            sessions, _, _ = await stack.enter_async_context(clients(dsn))
            stack.enter_context(patch.object(ScriptedConversationModel, 'classify', capture))
            a, b = sessions[:2]
            ac, bc = await conversation(a), await conversation(b)
            bc = await say(b, bc, 'PRIVATE-MANAGER-CONTEXT')
            assert contexts[-1][0] == 'safety_manager'
            task = (await start(a))['task_id']
            ac = await bind(a, ac, task)
            ac = await say(a, ac, 'PRIVATE-APPLICANT-CONTEXT')
            await send(a, task, 'submit', command(reviewer_user_id='reviewer'))
            bc = await bind(b, bc, task)
            bc = await say(b, bc, '你好')
            manager_context = contexts[-1][1]
            assert 'PRIVATE-APPLICANT-CONTEXT' not in manager_context
            assert 'PRIVATE-MANAGER-CONTEXT' in manager_context
            assert ac['conversation_id'] not in manager_context
            assert all(key not in manager_context for key in (
                'checkpoint', 'thread_id', 'error_details', 'raw_evidence'))
    run(scenario())


@pytest.mark.parametrize('intent,payload,stage', [
    ('submit_application', {'reviewer_user_id': 'reviewer'}, 'draft'),
    ('request_changes', {'questions': ['具体位置？']}, 'under_review'),
    ('resubmit_application', {'reply': '已补充'}, 'changes_requested'),
    ('complete_material_review', {'conclusion': '人工核对完成'}, 'under_review'),
])
def test_each_structured_card_freezes_payload_rejects_and_expires(dsn, intent, payload, stage):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            a, b = sessions[:2]
            task = (await start(a))['task_id']
            if stage != 'draft':
                await send(a, task, 'submit', command(reviewer_user_id='reviewer'))
            if stage == 'changes_requested':
                await send(b, task, 'request_changes', command(2, questions=['补充位置']))
                assert (await a.post(f'/tasks/{task}/revise', json={
                    'request_id': 'patch', 'expected_revision': 1, 'fields': PATCH}
                )).status_code == 200
            actor = a if intent in ('submit_application', 'resubmit_application') else b
            conv = await bind(actor, await conversation(actor), task)
            path = f"/conversations/{conv['conversation_id']}/collaboration-candidates"

            async def card():
                response = await actor.post(path, json={
                    'request_id': uuid4().hex, 'expected_revision': conv['revision'],
                    'intent': intent, 'collaboration': payload})
                assert response.status_code == 200, response.text
                return response.json()

            conv = await card()
            frozen = conv['pending_intent']['collaboration']
            for key, value in payload.items():
                assert frozen['payload'][key] == value
            conv = await say(actor, conv, '他说“确认”是什么意思？')
            assert conv['pending_intent']['collaboration'] == frozen
            conv = await say(actor, conv, '不确认')
            assert conv['pending_intent'] is None
            conv = await card()
            frozen = conv['pending_intent']['collaboration']
            if stage == 'draft':
                await send(a, task, 'submit', command(reviewer_user_id='reviewer'))
            elif stage == 'changes_requested':
                await send(a, task, 'resubmit', command(3, 2, reply='另一窗口重提'))
            else:
                await send(b, task, 'request_changes', command(2, questions=['另一窗口已退回']))
            await say(actor, conv, '确认', status=409)
            raw = (await actor.get(f"/conversations/{conv['conversation_id']}")).json()
            assert raw['pending_intent']['collaboration'] == frozen
    run(scenario())


def test_nested_shared_projection_is_allowlisted_at_model_boundary():
    context = ConversationContext(status='active_hot_work', collaboration_role='safety_manager',
        task_projection={'task_id': 'shared-task', 'collaboration': {
            'application': {'status': 'under_review', 'version': 2,
                            'checkpoint': 'PRIVATE-CHECKPOINT'},
            'events': [{'event_id': 'business-1', 'action': 'request_changes',
                        'payload': {'questions': ['具体点位'], 'private_chat': 'PRIVATE-CHAT'}}],
            'allowed_actions': ['request_changes'], 'private_trace': 'PRIVATE-TRACE'}})
    value = serialize_context(context)
    assert '具体点位' in value
    assert all(sentinel not in value for sentinel in (
        'PRIVATE-CHECKPOINT', 'PRIVATE-CHAT', 'PRIVATE-TRACE'))
    assert len(value.encode()) <= 16 * 1024


def test_structured_candidate_request_id_compares_complete_payload(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            actor = sessions[0]
            task = (await start(actor))['task_id']
            conv = await bind(actor, await conversation(actor), task)
            path = f"/conversations/{conv['conversation_id']}/collaboration-candidates"
            body = {'request_id': 'same-candidate', 'expected_revision': conv['revision'],
                    'intent': 'submit_application',
                    'collaboration': {'reviewer_user_id': 'reviewer'}}
            first = await actor.post(path, json=body)
            assert first.status_code == 200
            assert (await actor.post(path, json=body)).json() == first.json()
            body['collaboration']['reviewer_user_id'] = 'unassigned'
            conflict = await actor.post(path, json=body)
            assert conflict.status_code == 409, conflict.text
    run(scenario())


@pytest.mark.parametrize('actor_index', [0, 1])
def test_pause_resume_only_guidance_for_shared_review(dsn, actor_index):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            task = (await start(sessions[0]))['task_id']
            await send(sessions[0], task, 'submit', command(reviewer_user_id='reviewer'))
            actor = sessions[actor_index]
            conv = await bind(actor, await conversation(actor), task)
            conv = await say(actor, conv, '暂停当前任务')
            assert conv['status'] == 'paused'
            conv = await say(actor, conv, '继续任务')
            assert conv['status'] == 'active_hot_work'
            assert conv['task_projection']['revision'] == 1
    run(scenario())


def test_new_applicant_material_analysis_does_not_claim_automatic_submission(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            actor = sessions[0]
            conv = await say(actor, await conversation(actor),
                '申请动火，作业位置在SYNTHETIC台架，作业对象是SYNTHETIC试件，'
                '作业方式是焊接演示，附件是SYNTHETIC示意图')
            conv = await say(actor, conv, '确认申请')
            assert conv['task_projection']['collaboration']['application']['status'] == 'draft'
            assert '已进入人工复核' not in conv['messages'][-1]['text']
            assert '待提交' in conv['messages'][-1]['text']
    run(scenario())


def test_shared_readers_wait_boundedly_for_transient_task_contention(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            a = sessions[0]
            task = (await start(a))['task_id']
            conv = await bind(a, await conversation(a), task)
            original = PostgresRegistry.locked
            busy_actions = set()

            @asynccontextmanager
            async def first_read_busy(registry, actor, task_id, *, action='owner_read'):
                if task_id == task and action not in busy_actions:
                    busy_actions.add(action)
                    raise TaskBusy('controlled short read-side contention')
                async with original(registry, actor, task_id, action=action) as record:
                    yield record

            with patch.object(PostgresRegistry, 'locked', first_read_busy):
                snapshot = (await a.get(f"/conversations/{conv['conversation_id']}")).json()
                assert snapshot['task_projection']['status'] != 'unavailable'
                events = await a.get(f'/console/api/tasks/{task}/events')
                assert events.status_code == 200, events.text
            assert busy_actions == {'read', 'read_events'}
    run(scenario())


@pytest.mark.parametrize('revocation', ['legacy_role', 'lost_participation'])
@pytest.mark.parametrize('resource_path', ['active', 'projection', 'pending', 'business'])
def test_revoked_shared_content_cannot_replay_from_any_cached_resource_path(
    dsn, revocation, resource_path,  # noqa: F811
):
    async def scenario():
        async with clients(dsn) as (sessions, _, config):
            a, b = sessions[:2]
            task = (await start(a))['task_id']
            await send(a, task, 'submit', command(reviewer_user_id='reviewer'))
            conv = await bind(b, await conversation(b), task)
            arguments = {'request_id': 'cached-shared-message',
                         'expected_revision': conv['revision'], 'text': '你好'}
            path = f"/conversations/{conv['conversation_id']}/messages"
            response = await b.post(path, json=arguments)
            assert response.status_code == 200
            cached = response.json()
            if resource_path != 'active':
                cached['active_task_id'] = None
                if resource_path != 'projection':
                    cached['task_projection'] = None
                if resource_path != 'business':
                    cached['business_messages'] = []
                if resource_path == 'pending':
                    cached['pending_intent'] = {'collaboration': {
                        'task_id': task, 'action': 'request_changes', 'payload': command(
                            2, questions=['已撤权的旧卡片'])}}
                async with await EventStore(dsn).connect() as conn:
                    await conn.execute('UPDATE anlan_v2.conversation_messages SET result=%s '
                        'WHERE conversation_id=%s AND request_id=%s',
                        (Jsonb(cached), conv['conversation_id'], arguments['request_id']))
            if revocation == 'legacy_role':
                config.tokens[1].collaboration_role = None
            else:
                # Controlled revocation fixture, not a product reassignment command.
                async with await EventStore(dsn).connect() as conn:
                    await conn.execute('UPDATE anlan_v2.collaboration_applications '
                        "SET reviewer_user_id='unassigned' WHERE task_id=%s", (task,))
            current = (await b.get(f"/conversations/{conv['conversation_id']}")).json()
            assert current['task_projection']['status'] == 'unavailable'
            assert (await b.post(path, json=arguments)).status_code == 404
    run(scenario())


def test_legacy_owner_private_message_replay_remains_compatible(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            actor = sessions[4]
            task = (await start(actor))['task_id']
            conv = await bind(actor, await conversation(actor), task)
            body = {'request_id': 'legacy-replay', 'expected_revision': conv['revision'],
                    'text': '你好'}
            path = f"/conversations/{conv['conversation_id']}/messages"
            first = await actor.post(path, json=body)
            assert first.status_code == 200
            assert (await actor.post(path, json=body)).json() == first.json()
    run(scenario())


def test_applicant_keeps_semantic_followups_after_creation_and_supplement(dsn):  # noqa: F811
    async def scenario():
        class SemanticDouble:
            calls = 0

            async def analyze(self, application):
                self.calls += 1
                name, question = (
                    ('work_location_description', '请说明台架的具体东侧点位。') if self.calls == 1
                    else ('work_method_description', '请明确本轮焊接方式与隔离方法。'))
                return Analysis(semantic_status='checked', issues=[Issue(
                    field=name, kind='ambiguous' if self.calls == 1 else 'missing_detail',
                    quote=getattr(application, name), reason='SYNTHETIC语义替身要求具体信息',
                    question=question, source='model')])

        model = SemanticDouble()
        async with AsyncExitStack() as stack:
            stack.enter_context(patch('anlan.interfaces.service_models.OfflineAnalyzer',
                                      return_value=model))
            sessions, _, _ = await stack.enter_async_context(clients(dsn))
            actor = sessions[0]
            conv = await say(actor, await conversation(actor),
                '申请动火，作业位置在SYNTHETIC台架，作业对象是SYNTHETIC试件，'
                '作业方式是焊接演示，附件是SYNTHETIC示意图')
            conv = await say(actor, conv, '确认申请')
            task = conv['task_projection']
            assert task['missing_fields'] == [] and task['status'] == 'waiting_input'
            assert task['semantic_status'] == 'checked'
            assert task['issue_questions'] == ['请说明台架的具体东侧点位。']
            conv = await say(actor, conv, '作业位置在SYNTHETIC台架东侧1号点位')
            assert conv['task_projection']['revision'] == 2
            assert conv['task_projection']['issue_questions'] == ['请明确本轮焊接方式与隔离方法。']
            assert '请明确本轮焊接方式与隔离方法。' in conv['messages'][-1]['text']
            contexts = []
            original = ScriptedConversationModel.classify

            async def capture(subject, context, **kwargs):
                contexts.append(serialize_context(context))
                return await original(subject, context, **kwargs)

            with patch.object(ScriptedConversationModel, 'classify', capture):
                await say(actor, conv, '你好')
            assert '请明确本轮焊接方式与隔离方法。' in contexts[-1]
            assert model.calls == 2  # Reads never repeat analysis/model calls.
    run(scenario())


@pytest.mark.parametrize('semantic', ['failed', 'offline_not_checked', 'checked'])
def test_applicant_analysis_status_is_preserved_and_failure_is_not_claimed_complete(
    dsn, semantic,  # noqa: F811
):
    async def scenario():
        class StatusDouble:
            async def analyze(self, _application):
                return Analysis(semantic_status=semantic,
                                error='PRIVATE-ANALYSIS-ERROR' if semantic == 'failed' else None)

        async with AsyncExitStack() as stack:
            stack.enter_context(patch('anlan.interfaces.service_models.OfflineAnalyzer',
                                      return_value=StatusDouble()))
            sessions, _, _ = await stack.enter_async_context(clients(dsn))
            actor = sessions[0]
            conv = await say(actor, await conversation(actor),
                '申请动火，作业位置在SYNTHETIC台架，作业对象是SYNTHETIC试件，'
                '作业方式是焊接演示，附件是SYNTHETIC示意图')
            conv = await say(actor, conv, '确认申请')
            assert conv['task_projection']['semantic_status'] == semantic
            assert 'PRIVATE-ANALYSIS-ERROR' not in str(conv)
            if semantic == 'failed':
                assert '分析已完成' not in conv['messages'][-1]['text']
            if semantic == 'offline_not_checked':
                assert '语义未核查' in conv['messages'][-1]['text']
    run(scenario())
def test_business_status_answers_are_private_and_authorized(dsn):  # noqa: F811
    async def scenario():
        from anlan.infrastructure.business_queries import BusinessQueryAuditStore

        async with clients(dsn) as (sessions, actors, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            a = await bind(applicant, await conversation(applicant), task)
            a = await say(applicant, a, "PRIVATE-APPLICANT 私聊")
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            b = await bind(reviewer, await conversation(reviewer), task)
            b = await say(reviewer, b, "PRIVATE-REVIEWER 私聊")
            audit = BusinessQueryAuditStore(dsn)

            async def counts():
                async with await audit.connect() as conn:
                    values = []
                    for table in ("anlan_operations", "collaboration_commands",
                                  "collaboration_events"):
                        # Identifiers are a fixed test-owned tuple, never request input.
                        row = await (await conn.execute(
                            f"SELECT count(*) AS n FROM anlan_v2.{table} WHERE task_id=%s",
                            (task,))).fetchone()
                        values.append(row["n"])
                    row = await (await conn.execute(
                        "SELECT count(*) AS n FROM anlan_v2.collaboration_notifications n "
                        "JOIN anlan_v2.collaboration_events e USING(tenant_id,event_id) "
                        "WHERE e.task_id=%s", (task,))).fetchone()
                    values.append(row["n"])
                    row = await (await conn.execute(
                        "SELECT count(*) AS n FROM anlan_v2.pending_intents "
                        "WHERE conversation_id=ANY(%s)",
                        ([a["conversation_id"], b["conversation_id"]],))).fetchone()
                    values.append(row["n"])
                    return values

            before = await counts()
            a = await say(applicant, a, "当前材料状态是什么？APPLICANT-QUERY")
            b = await say(reviewer, b, "当前材料状态是什么？REVIEWER-QUERY")
            assert await counts() == before
            for result in (a, b):
                answer = result["messages"][-1]["text"]
                assert task in answer and "材料版本 1" in answer and "申请版本 2" in answer
                assert "安全审核中" in answer and "PRIVATE" not in answer
                assert result["pending_intent"] is None
            assert "PRIVATE-APPLICANT" not in str(b) and "PRIVATE-REVIEWER" not in str(a)
            assert "APPLICANT-QUERY" not in str(b) and "REVIEWER-QUERY" not in str(a)
            assert not ({m["message_id"] for m in a["messages"]} &
                        {m["message_id"] for m in b["messages"]})
            for actor, result in zip(actors[:2], (a, b)):
                source = next(m for m in reversed(result["messages"]) if m["role"] == "user")
                receipt = await audit.get(actor, source["message_id"])
                assert receipt["material_revision"] == 1 and receipt["application_version"] == 2
                assert receipt["outcome"] == "ok" and receipt["citation_ids"] == []
                assert not {"question", "answer", "facts", "citations"} & receipt.keys()
            assert (await reviewer.get(f"/tasks/{task}/history")).status_code == 404
    run(scenario())


def test_unauthorized_queries_and_audit_failure_disclose_no_business_facts(dsn):  # noqa: F811
    async def scenario():
        from anlan.infrastructure.business_queries import BusinessQueryAuditStore

        async with clients(dsn) as (sessions, _, _):
            task = (await start(sessions[0]))["task_id"]
            await send(sessions[0], task, "submit", command(reviewer_user_id="reviewer"))
            for actor in (sessions[2], sessions[3], sessions[5]):
                conv = await conversation(actor)
                result = await say(actor, conv, f"申请 {task} 当前状态是什么？")
                assert result == {"error_category": "query_failure"}
                conv = (await actor.get(f"/conversations/{conv['conversation_id']}")).json()
                result = await say(actor, conv, "申请 nonexistent-task 当前状态是什么？")
                assert result == {"error_category": "query_failure"}
            conv = await bind(sessions[0], await conversation(sessions[0]), task)
            with patch.object(BusinessQueryAuditStore, "record",
                              side_effect=RuntimeError("PRIVATE")):
                result = await say(sessions[0], conv, "当前状态是什么？")
            assert result == {"error_category": "query_failure"}
    run(scenario())

def test_mixed_query_material_and_collaboration_wait_for_confirmation(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            a = await bind(applicant, await conversation(applicant), task)
            a = await say(applicant, a, "当前材料状态是什么？另外把作业位置改成二号罐区。")
            assert "当前" in a["messages"][-1]["text"]
            assert a["pending_intent"]["kind"] == "task_input_candidate"
            assert a["pending_intent"]["fields"] == {"work_location_description": "二号罐区"}
            assert a["task_projection"]["revision"] == 1
            args = (applicant, a, "确认")
            a = await say(*args, request_id="confirm-mixed")
            assert a["task_projection"]["revision"] == 2
            assert await say(*args, request_id="confirm-mixed") == a
            a = await say(applicant, a, "当前状态是什么？提交申请给 reviewer")
            frozen = a["pending_intent"]["collaboration"]
            assert frozen["payload"]["expected_material_revision"] == 2
            assert frozen["payload"]["expected_application_version"] == 1
            a = await say(applicant, a, "确认")
            b = await bind(reviewer, await conversation(reviewer), task)
            b = await say(reviewer, b, "当前状态是什么？把位置改成三号罐区。")
            assert b["pending_intent"] is None
            assert "无权修改材料" in b["messages"][-1]["text"]
            assert b["task_projection"]["revision"] == 2
    run(scenario())

def test_explicit_unbound_query_replay_reauthorizes_after_role_revocation(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, config):
            applicant, reviewer = sessions[:2]
            task = (await start(applicant))["task_id"]
            await send(applicant, task, "submit", command(reviewer_user_id="reviewer"))
            conv = await conversation(reviewer)
            text = f"申请 {task} 当前材料状态是什么？"
            answer = await say(reviewer, conv, text, request_id="explicit-query")
            assert answer["active_task_id"] is None
            assert answer["query_reference"]["task_id"] == task
            config.tokens[1].collaboration_role = None
            await say(reviewer, conv, text, request_id="explicit-query", status=404)
    run(scenario())


def test_long_details_answer_fits_real_private_message_storage(dsn):  # noqa: F811
    async def scenario():
        from test_material_revisions import COMPLETE

        async with clients(dsn) as (sessions, _, _):
            actor = sessions[0]
            fields = COMPLETE | {"work_location_description": "位" * 2000,
                                 "work_object_description": "管" * 2000}
            task = (await start(actor, fields))["task_id"]
            conv = await bind(actor, await conversation(actor), task)
            conv = await say(actor, conv, "作业对象是什么？")
            text = conv["messages"][-1]["text"]
            assert len(text.encode("utf-8")) <= 7600 and "已截断" in text
            assert task in text and "材料版本 1" in text and "申请版本 1" in text
    run(scenario())

