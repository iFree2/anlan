"""Shared synthetic events retain the real actor and immutable raw alarm."""

from uuid import uuid4

import pytest
from test_collaboration_api import clients, command, send, settings, start
from test_events_postgres import dsn, run  # noqa: F401
from test_material_revisions import PATCH
from test_perception_postgres import REFS

from anlan.infrastructure.events import EventStore
from anlan.interfaces.service_config import ServiceConfig

pytestmark = pytest.mark.postgres


def event_settings():
    config, actors, tokens = settings()
    return ServiceConfig.model_validate(config.model_dump() | {'console_profiles': [
        {'identity': actors[1].model_dump(), 'references': REFS}]}), actors, tokens


async def submitted(sessions):
    task = (await start(sessions[0]))['task_id']
    await send(sessions[0], task, 'submit', command(reviewer_user_id='reviewer'))
    return task


async def simulate(client, task, revision=1):
    response = await client.post(f'/console/api/tasks/{task}/events', json={
        'request_id': uuid4().hex, 'expected_revision': revision, 'kind': 'helmet_missing'})
    assert response.status_code == 200, response.text
    return response.json()


def test_shared_event_review_feedback_actor_scope_currentness_and_alarm(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn, event_settings()) as (sessions, actors, _):
            applicant, reviewer = sessions[:2]
            task = await submitted(sessions)
            event = await simulate(reviewer, task)
            assert event['actor'] == actors[1].model_dump()
            receipt = event['receipt_id']
            response = await reviewer.post(f'/console/api/events/{receipt}/reviews', json={
                'request_id': 'review'})
            assert response.status_code == 200, response.text
            review = response.json()
            assert review['result']['status'] == 'completed'
            assert review['actor'] == actors[1].model_dump()
            assert review['currentness'] == 'current'
            assert 'context' not in str(review['result']['report'].keys())
            rid = review['review_id']
            result = await reviewer.post(f'/reviews/{rid}/feedback', json={
                'request_id': 'feedback', 'expected_revision': 1, 'decision': 'confirmed_event'})
            assert result.status_code == 200, result.text
            assert result.json()['feedback']['actor'] == actors[1].model_dump()
            # The database scope remains the applicant; audit and fixed collection use the actor.
            async with await EventStore(dsn).connect() as conn:
                row = await (await conn.execute(
                    'SELECT user_id,document,result FROM anlan_v2.perception_reviews '
                    'WHERE review_id=%s', (rid,))).fetchone()
                assert row['user_id'] == actors[0].user_id
                assert row['document']['actor'] == actors[1].model_dump()
                report = row['result']['report']
                assert len(report['observations']) == 3
                assert report['collection']['mode'] == 'fixed_parallel_branches'
                assert all(child['input']['identity'] == actors[1].model_dump()
                           for child in report['collection']['children'])
                audits = await (await conn.execute(
                    'SELECT actor_user_id,action FROM anlan_v2.collaboration_events '
                    'WHERE task_id=%s ORDER BY created_at', (task,))).fetchall()
                assert [(item['actor_user_id'], item['action']) for item in audits][-2:] == [
                    ('reviewer', 'run_event_review'), ('reviewer', 'record_event_feedback')]
            assert (await applicant.get(f'/reviews/{rid}')).status_code == 200
            for outsider in sessions[2:]:
                for path in (f'/events/{receipt}', f'/reviews/{rid}',
                             f'/console/api/tasks/{task}/events',
                             f'/console/api/events/{receipt}/reviews',
                             f'/events/{receipt}/stream', f'/reviews/{rid}/stream'):
                    assert (await outsider.get(path)).status_code == 404, path
            await send(reviewer, task, 'request_changes', command(2, questions=['补充位置']))
            assert (await applicant.post(f'/tasks/{task}/revise', json={
                'request_id': 'patch', 'expected_revision': 1, 'fields': PATCH})).status_code == 200
            old = (await applicant.get(f'/reviews/{rid}')).json()
            assert old['currentness'] == 'stale_material'
            rejected = await reviewer.post(f'/reviews/{rid}/feedback', json={
                'request_id': 'stale-feedback', 'expected_revision': 2,
                'decision': 'needs_verification'})
            assert rejected.status_code == 409
            raw = (await applicant.get(f'/events/{receipt}')).json()
            assert raw['raw']['alarm_state'] == 'active'
            assert all(private not in str(raw) for private in ('run_id', 'body_hash'))
    run(scenario())


def test_shared_event_time_and_superseding_checks_remain_authoritative(dsn):  # noqa: F811
    async def scenario():
        from datetime import timedelta

        from anlan.interfaces.perception_runtime import PerceptionRuntime

        async with clients(dsn, event_settings()) as (sessions, actors, config):
            task = await submitted(sessions)
            event = await simulate(sessions[1], task)
            receipt = event['receipt_id']
            review = await sessions[1].post(f'/console/api/events/{receipt}/reviews', json={
                'request_id': 'time-review'})
            assert review.status_code == 200
            rid = review.json()['review_id']
            future = PerceptionRuntime(dsn, clock=lambda: config.as_of + timedelta(minutes=11),
                                       access_config=config)
            assert (await future.get(actors[1], rid))['currentness'] == 'expired_event'
            await simulate(sessions[1], task)
            current = (await sessions[0].get(f'/reviews/{rid}')).json()
            assert current['currentness'] == 'superseded_event'
            assert (await sessions[0].get(f'/events/{receipt}')).json()['raw'][
                'alarm_state'] == 'active'
    run(scenario())


def test_only_assigned_manager_mutates_events_and_no_client_source_injection(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn, event_settings()) as (sessions, _, _):
            task = await submitted(sessions)
            for actor in [sessions[0], *sessions[2:]]:
                assert (await actor.post(f'/console/api/tasks/{task}/events', json={
                    'request_id': 'no', 'expected_revision': 1,
                    'kind': 'gas_abnormal'})).status_code == 404
            event = await simulate(sessions[1], task)
            receipt = event['receipt_id']
            for actor in [sessions[0], *sessions[2:]]:
                assert (await actor.post(f'/events/{receipt}/process', json={})).status_code == 404
                assert (await actor.post(f'/events/{receipt}/reviews', json={
                    'request_id': 'no'})).status_code == 404
            assert (await sessions[1].post('/sources/arbitrary/events', json={})).status_code == 404
            assert (await sessions[1].post(f'/console/api/tasks/{task}/events', json={
                'request_id': 'injected', 'expected_revision': 1, 'kind': 'gas_abnormal',
                'storage_scope': 'applicant'})).status_code == 422
    run(scenario())
