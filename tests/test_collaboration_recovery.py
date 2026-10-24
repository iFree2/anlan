"""Recovery windows use real PostgreSQL; process restart is covered by release Gate."""

import asyncio
from unittest.mock import patch

import httpx
import pytest
from test_collaboration_api import clients, command, send, start
from test_collaboration_conversation import bind, conversation, say
from test_collaboration_store import setup
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import COMPLETE

from anlan.infrastructure.conversations import ConversationStore
from anlan.infrastructure.postgres import PostgresRegistry
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import start_task_id

pytestmark = pytest.mark.postgres


def test_empty_checkpoint_binding_and_snapshot_require_explicit_recovery(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, actors, config):
            applicant = sessions[0]
            request_id = 'crash-before-first-reserve'
            task = start_task_id(actors[0], request_id)

            async def crash(*args, **kwargs):
                raise RuntimeError('process lost before reserve')

            with patch.object(PostgresRegistry, 'reserve', crash):
                with pytest.raises(RuntimeError, match='before reserve'):
                    await applicant.post('/tasks', json={
                        'request_id': request_id, 'fields': COMPLETE})
            async with postgres_service(dsn, OfflineAnalyzer(), access_config=config) as service:
                async with service._registry.locked(actors[0], task, action='read') as record:
                    assert not (await service._snapshot(record)).values
                    assert await service._registry.pending(task) is None
                    assert record.identity == actors[0]
            conv = await conversation(applicant)
            await bind(applicant, conv, task, status=409)
            # An earlier persisted binding must also render a controlled unavailable state.
            await ConversationStore(dsn).bind_task(
                actors[0], conv['conversation_id'], conv['revision'], task)
            response = await applicant.get(f"/conversations/{conv['conversation_id']}")
            assert response.status_code == 200
            assert response.json()['task_projection']['status'] == 'unavailable'
            candidate = await applicant.post(
                f"/conversations/{conv['conversation_id']}/collaboration-candidates", json={
                    'request_id': 'empty-checkpoint-candidate',
                    'expected_revision': response.json()['revision'],
                    'intent': 'submit_application',
                    'collaboration': {'reviewer_user_id': 'reviewer'}})
            assert candidate.status_code == 409
            assert (await applicant.get(f'/collaboration/applications/{task}')).status_code == 409
            assert (await sessions[1].post(f'/tasks/{task}/recover')).status_code == 404
            recovered = await applicant.post(f'/tasks/{task}/recover')
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()['task_id'] == task
            assert recovered.json()['revision'] == 1
            bound = await applicant.get(f"/conversations/{conv['conversation_id']}")
            assert bound.json()['task_projection']['status'] == 'awaiting_review'
            listing = (await applicant.get('/collaboration/applications')).json()['items']
            assert [item['task_id'] for item in listing] == [task]
    run(scenario())


def test_concurrent_draft_registration_handles_all_unique_indexes(dsn):  # noqa: F811
    async def scenario():
        store, owner, _, state = await setup(dsn)
        # Repeated real speculative inserts exercise both task and tenant/task indexes.
        # Each fresh task is private and has no collaboration row before this wave.
        for _ in range(20):
            async with postgres_service(dsn, OfflineAnalyzer()) as workflow:
                state = await workflow.start(owner, COMPLETE)
            applications = await asyncio.gather(*[
                store.ensure_draft(owner, 'applicant', state['task_id']) for _ in range(8)])
            assert all(app == applications[0] for app in applications)
            assert applications[0].version == 1
    run(scenario())


def test_reconnect_cursors_and_direct_http_cannot_cross_participants(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, config):
            a, b = sessions[:2]
            task = (await start(a))['task_id']
            ca = await bind(a, await conversation(a), task)
            ca = await say(a, ca, 'PRIVATE-APPLICANT-B4-SENTINEL')
            await send(a, task, 'submit', command(reviewer_user_id='reviewer'))
            cb = await bind(b, await conversation(b), task)
            assert 'PRIVATE-APPLICANT-B4-SENTINEL' not in str(cb)
            first = (await b.get('/collaboration/notifications')).json()
            cursor = first['next_cursor']
            assert len(first['items']) == 1
            for outsider in sessions[2:]:
                for path in (f'/tasks/{task}', f'/tasks/{task}/stream',
                             f'/collaboration/applications/{task}',
                             f"/conversations/{ca['conversation_id']}",
                             f"/conversations/{ca['conversation_id']}/stream"):
                    assert (await outsider.get(path)).status_code == 404
                assert (await outsider.post(f'/tasks/{task}/recover')).status_code == 404
                inbox = await outsider.get('/collaboration/notifications', params={'after': 0})
                assert inbox.status_code == 404 or inbox.json()['items'] == []
            async with httpx.AsyncClient(transport=a._transport, base_url='http://test') as anon:
                for path in (f'/tasks/{task}', f'/tasks/{task}/stream',
                             '/collaboration/notifications',
                             f"/conversations/{ca['conversation_id']}/stream"):
                    assert (await anon.get(path)).status_code == 401
            await send(b, task, 'request_changes', command(2, questions=['东侧具体点位']))
            assert (await b.get('/collaboration/notifications', params={
                'after': cursor})).json()['items'] == []
            assert len((await a.get('/collaboration/notifications')).json()['items']) == 1
            # Grant downgraded to None cannot replay data via old HTTP or SSE entry points.
            config.tokens[1].collaboration_role = None
            for path in (f'/tasks/{task}', f'/tasks/{task}/stream',
                         f'/collaboration/applications/{task}', '/collaboration/notifications'):
                assert (await b.get(path)).status_code == 404
            restored = (await b.get(f"/conversations/{cb['conversation_id']}")).json()
            assert restored['task_projection']['status'] == 'unavailable'
            assert restored['business_messages'] == []
            assert '东侧具体点位' not in str(restored['task_projection'])
    run(scenario())
