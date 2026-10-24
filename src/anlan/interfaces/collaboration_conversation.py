"""Role-aware conversation boundary; only confirmed frozen commands can mutate."""

from anlan.collaboration.policy import authorize
from anlan.collaboration.service import COMMANDS
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.conversation.contracts import COLLABORATION_INTENTS, FrozenCollaborationCommand
from anlan.interfaces.conversation_runtime import (
    TaskProjection,
    WorkflowResult,
    _project,
    _request_id,
    bounded_read,
)
from anlan.workflows.material_contracts import Application


class CollaborationConversationAdapter:
    def __init__(self, service, workflow):
        self.service, self.workflow = service, workflow

    def role(self, actor):
        return self.service.config.collaboration_role(actor)

    async def read(self, actor, task_id):
        if self.role(actor) is None:
            return await self.workflow.read(actor, task_id)
        return await bounded_read(lambda: self._read(actor, task_id))

    async def _read(self, actor, task_id):
        # One authorized task lock and checkpoint read: owner guidance and shared metadata
        # cannot be taken from different material/application versions.
        async with self.service.service_context_factory() as workflow:
            async with workflow._registry.locked(actor, task_id, action='read') as record:
                conn = workflow._registry.conn
                app = await self.service.store.get(actor, self.role(actor), task_id, conn=conn)
                material = (await workflow._snapshot(record)).values
                if not material:
                    raise InvalidTransition('任务尚未写入 checkpoint；请执行 recover')
                events = await self.service.store.events(conn, app)
                if self.role(actor) == 'applicant' and actor == record.identity:
                    projection = _project(material)
                else:
                    fields = Application.model_validate(material.get('fields', {})).model_dump()
                    projection = TaskProjection(
                        task_id=task_id, status=material['status'], revision=material['revision'],
                        fields={k: v for k, v in fields.items() if v},
                        missing_fields=[k for k, v in fields.items() if not v],
                        analysis_mode=material['analysis_mode'], semantic_status='shared_materials',
                        recoverable=False)
        actions = []
        for action in ('edit_materials', *COMMANDS, 'run_event_review', 'record_event_feedback'):
            try:
                authorize(actor, self.role(actor), app, action)
            except (AccessDenied, InvalidTransition):
                continue
            actions.append(action)
        return WorkflowResult(projection=projection.model_copy(update={
            'collaboration': {'application': app.model_dump(mode='json'),
                              'events': events, 'allowed_actions': actions,
                              'notice': '材料核查完成不代表作业批准或开工授权'}}))

    async def freeze(self, actor, conversation_id, message_id, task_id, proposal):
        shared = await self.service.get(actor, task_id)
        action = COLLABORATION_INTENTS[proposal.intent]
        app = shared['application']
        authorize(actor, self.role(actor), app, action)
        details = (proposal.collaboration.model_dump(exclude_none=True)
                   if proposal.collaboration else {})
        if not details.get('questions'):
            details.pop('questions', None)
        payload = COMMANDS[action].model_validate({
            'request_id': _request_id(conversation_id, message_id, action),
            'expected_application_version': app.version,
            'expected_material_revision': shared['materials']['revision'], **details,
        }).model_dump(mode='json')
        return FrozenCollaborationCommand(task_id=task_id, action=action, payload=payload)

    async def execute(self, actor, frozen):
        return await self.service.execute(actor, frozen.task_id, frozen.action, frozen.payload)

    async def notifications(self, actor, **kwargs):
        return await self.service.notifications(actor, **kwargs)

    async def start(self, *args, **kwargs):
        return await self.workflow.start(*args, **kwargs)

    async def submit(self, *args, **kwargs):
        return await self.workflow.submit(*args, **kwargs)

    async def recover(self, *args, **kwargs):
        return await self.workflow.recover(*args, **kwargs)

    def constrain(self, actor, proposal):
        if self.role(actor) == 'safety_manager' and proposal.intent in {
            'hot_work_candidate', 'task_input_candidate', 'switch_or_create_task'}:
            return proposal.model_copy(update={'intent': 'casual_chat', 'fields': {}})
        return proposal

    async def validate_cached(self, actor, result):
        # A role downgrade must not turn old shared snapshots into unguarded legacy cache.
        # Older/detached results may reference a resource without an active_task_id.
        projection = result.get('task_projection') or {}
        shared = projection.get('collaboration') or {}
        pending = (result.get('pending_intent') or {}).get('collaboration') or {}
        references = [result.get('active_task_id'), projection.get('task_id'),
                      (shared.get('application') or {}).get('task_id'), pending.get('task_id')]
        references.extend(event.get('task_id') for event in result.get('business_messages', []))
        for task_id in sorted({value for value in references if isinstance(value, str) and value}):
            # Original authorized workflow read preserves legacy owner-only compatibility,
            # and checks persisted collaboration participation even when role is now None.
            await bounded_read(lambda: self.workflow.read(actor, task_id))
