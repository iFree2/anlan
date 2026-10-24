"""Resolve event storage only after checking the real actor's task permission."""

from uuid import uuid4

from anlan.collaboration.access import TaskAccess
from anlan.collaboration.policy import authorize
from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.collaboration import CollaborationStore


class EventAccess:
    def __init__(self, config=None):
        self.tasks = TaskAccess(config)
        self.config = config

    async def scope(self, conn, actor, task_id, action):
        cursor = await conn.execute(
            'SELECT tenant_id,user_id FROM anlan_v2.anlan_tasks WHERE task_id=%s', (task_id,))
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied('任务不存在或无权访问')
        scope = Identity.model_validate(row)
        await self.tasks.check(conn, actor, scope, task_id, action)
        return scope

    async def resource(self, conn, actor, key, *, review=False, action='read_events'):
        # Fixed SQL identifiers; tenant predicate precedes even internal document inspection.
        query = ('SELECT user_id,document FROM anlan_v2.perception_reviews '
                 'WHERE review_id=%s AND tenant_id=%s' if review else
                 'SELECT user_id,document FROM anlan_v2.perception_events '
                 'WHERE receipt_id=%s AND tenant_id=%s')
        cursor = await conn.execute(query, (key, actor.tenant_id))
        row = await cursor.fetchone()
        if row is None:
            raise AccessDenied('记录不存在或无权访问')
        doc = row['document']
        task_id = doc.get('task_id') if review else (doc.get('binding') or {}).get('task_id')
        if self.tasks.role(actor) is None:
            if row['user_id'] != actor.user_id:
                raise AccessDenied('记录不存在或无权访问')
            if task_id:
                app = await self.tasks.application(conn, task_id)
                if app is not None:
                    # A revoked collaboration role never becomes an owner-only event grant.
                    authorize(actor, None, app, action)
            # Legacy receipts belong to their receiver even if their target task was
            # missing/misbound. Association still checks that task and records unavailable.
            return actor
        if task_id:
            scope = await self.scope(conn, actor, task_id, action)
            if scope.user_id != row['user_id']:
                raise AccessDenied('记录资源范围不一致')
            return scope
        if self.tasks.role(actor) is not None or row['user_id'] != actor.user_id:
            raise AccessDenied('记录不存在或无权访问')
        return actor

    async def audit(self, conn, actor, task_id, action, revision, payload):
        if self.tasks.role(actor) is None:
            return
        app = await self.tasks.application(conn, task_id)
        await self.scope(conn, actor, task_id, action)
        await CollaborationStore.append_event(conn, actor, self.tasks.role(actor), app,
                                               action, revision, payload, uuid4().hex)


def public_event(value):
    """No checkpoint run IDs, raw execution hashes or private errors cross the boundary."""
    binding = value.get('binding') or {}
    result = value.get('result')
    return {k: value[k] for k in ('receipt_id', 'source_id', 'raw', 'admission',
                                  'data_origin', 'received_at', 'actor') if k in value} | {
        'binding': {k: binding[k] for k in ('task_id', 'revision', 'object_ref', 'kind')
                    if k in binding},
        'result': ({k: result[k] for k in ('status', 'task_id', 'revision', 'processed_at')
                    if k in result} if result else None),
    }


def public_review(value):
    report = (value.get('result') or {}).get('report') or {}
    result = value.get('result')
    return {k: value[k] for k in ('review_id', 'receipt_id', 'task_id', 'material_revision',
                                  'data_origin', 'actor', 'created_at', 'revision',
                                  'currentness', 'cancel_requested') if k in value} | {
        'feedback': ({k: value['feedback'][k] for k in ('decision', 'recorded_at', 'actor')
                      if k in value['feedback']} if value.get('feedback') else None),
        'result': ({k: result[k] for k in ('status', 'currentness_at_finish', 'completed_at')
                    if k in result} | {'report': {
                        k: report[k] for k in ('candidate', 'observations', 'stop_reason', 'mode')
                        if k in report}} if result else None),
    }


class SharedCollectionReader:
    """Fixed collector uses real actor, safe materials and actor's own memories."""
    def __init__(self, service):
        self.service = service

    async def get(self, actor, task_id):
        value = await self.service.get(actor, task_id)
        # Collector metadata needs a source identifier; use a public revision identifier.
        fields = ('task_id', 'fields', 'status', 'revision', 'analysis_mode')
        return {k: value[k] for k in fields} | {
            'run_id': f"shared:{task_id}:v{value['revision']}"}
