"""One-message conversation orchestration with durable recovery boundaries."""

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.conversation.contracts import ConversationState, IntentProposal, PendingIntent
from anlan.conversation.policy import RouteAction, RouteDecision, decide
from anlan.llm.conversation import ConversationContext, VisibleMessage


class ConversationService:
    def __init__(self, store, model_factory, workflow):
        self.store = store
        self._model_factory = model_factory
        self.workflow = workflow

    async def create(self, identity, *, request_id):
        await self.store.initialize()
        created = await self.store.create(identity, request_id)
        return await self.snapshot_from_store(identity, created)

    async def list(self, identity, *, limit=20):
        return [
            await self.snapshot_from_store(identity, value)
            for value in await self.store.list(identity, limit)
        ]

    async def snapshot(self, identity, conversation_id):
        return await self.snapshot_from_store(
            identity, await self.store.get(identity, conversation_id)
        )

    async def message(
        self,
        identity,
        conversation_id,
        *,
        request_id,
        expected_revision,
        text,
    ):
        reservation = await self.store.reserve_message(
            identity, conversation_id, request_id, expected_revision, text
        )
        if reservation.get("result") is not None:
            return reservation["result"]
        async with self.store.operation_lock(
            identity, conversation_id, reservation["message_id"]
        ):
            raw = await self.store.get(identity, conversation_id)
            route = next(
                (
                    value
                    for value in raw["routes"]
                    if value["message_id"] == reservation["message_id"]
                ),
                None,
            )
            models = self._model_factory()
            projection = await self._task_projection(identity, raw)
            state = self._state(raw)
            context = self._context(raw, state, projection)
            if route is None:
                try:
                    proposal = await models.classifier.classify(
                        context, run_id=f"conversation:{reservation['message_id']}:classify"
                    )
                except Exception:
                    return await self.store.fail_message(
                        identity,
                        conversation_id,
                        reservation["message_id"],
                        "classifier_failure",
                    )
                decision = decide(state, proposal)
                await self.store.save_route(
                    identity,
                    conversation_id,
                    reservation["message_id"],
                    proposal,
                    decision,
                )
            else:
                proposal = IntentProposal.model_validate(route["proposal"])
                decision = RouteDecision.model_validate(route["decision"])
            try:
                result = await self._execute(
                    identity,
                    raw,
                    reservation,
                    proposal,
                    decision,
                    models,
                    projection,
                )
            except (InvalidTransition, TaskBusy, AccessDenied):
                await self.store.fail_message(
                    identity,
                    conversation_id,
                    reservation["message_id"],
                    "workflow_conflict",
                )
                raise
            except Exception:
                category = (
                    "chat_failure"
                    if decision.action is RouteAction.REPLY_ONLY
                    else "workflow_failure"
                )
                return await self.store.fail_message(
                    identity, conversation_id, reservation["message_id"], category
                )
            return await self.store.finish_message(
                identity, conversation_id, reservation["message_id"], result
            )

    async def _execute(
        self, identity, raw, reservation, proposal, decision, models, projection
    ):
        conversation_id = raw["conversation_id"]
        message_id = reservation["message_id"]
        action = decision.action
        assistant = None

        if action in {RouteAction.ASK_CONFIRMATION, RouteAction.ASK_TASK_INPUT_CONFIRMATION}:
            fields = dict(decision.fields)
            if raw["pending_intent"] is not None:
                fields = raw["pending_intent"]["candidate"].get("fields", {}) | fields
            candidate = proposal.model_dump(mode="json") | {"fields": fields}
            await self.store.set_pending_intent(
                identity, conversation_id, message_id, candidate
            )
            assistant = "请确认是否按以上信息继续；确认前不会创建或修改动火任务。"
        elif action is RouteAction.REJECT_PENDING_INTENT:
            await self.store.reject_pending_intent(identity, conversation_id)
            assistant = "已放弃这次待确认内容，没有修改动火任务。"
        elif action is RouteAction.START_HOT_WORK:
            workflow = await self.workflow.start(
                identity, conversation_id, message_id, decision.fields
            )
            await self.store.bind_task(
                identity, conversation_id, raw["revision"], workflow.projection.task_id
            )
            projection = workflow.projection.model_dump(mode="json")
            assistant = "已按你的确认创建动火材料任务；后续状态以侧栏为准。"
        elif action is RouteAction.SUBMIT_TASK_INPUT:
            if projection is None or decision.active_task_id is None:
                raise InvalidTransition("活动任务投影不可用")
            workflow = await self.workflow.submit(
                identity,
                conversation_id,
                message_id,
                decision.active_task_id,
                projection["revision"],
                decision.fields,
                projection["status"],
            )
            if raw["pending_intent"] is not None:
                await self.store.confirm_pending_intent(identity, conversation_id)
            projection = workflow.projection.model_dump(mode="json")
            assistant = "已提交补充材料；任务最新状态以侧栏为准。"
        elif action is RouteAction.PAUSE_TASK:
            await self.store.pause_task(identity, conversation_id)
            assistant = "已暂停当前会话中的任务引导，业务任务本身未被取消。"
        elif action is RouteAction.RECOVER_TASK:
            workflow = await self.workflow.recover(identity, decision.active_task_id)
            await self.store.activate_task(identity, conversation_id)
            projection = workflow.projection.model_dump(mode="json")
            assistant = "已恢复当前任务引导；任务最新状态以侧栏为准。"
        elif action is RouteAction.DETACH_TASK:
            await self.store.detach_task(identity, conversation_id)
            projection = None
            assistant = "已结束当前会话的任务引导，业务任务本身没有被修改。"
        elif action is RouteAction.ASK_TASK_SWITCH:
            assistant = "当前已有动火任务；请先结束当前引导，再发起新的任务申请。"
        elif action is RouteAction.REPLY_ONLY:
            reply = await models.responder.respond(
                self._context(raw, self._state(raw), projection),
                run_id=f"conversation:{message_id}:chat",
            )
            assistant = reply.text
        else:
            raise InvalidTransition("不支持的会话路由动作")

        await self.store.append_assistant_message(
            identity, conversation_id, message_id, assistant
        )
        return await self.snapshot(identity, conversation_id)

    async def snapshot_from_store(self, identity, raw):
        projection = await self._task_projection(identity, raw)
        visible = [
            {
                "message_id": item["message_id"],
                "ordinal": item["ordinal"],
                "role": item["role"],
                "text": item["text"],
                "status": item["status"],
            }
            for item in raw["messages"]
        ]
        source_pending = raw["pending_intent"]
        pending = None
        if source_pending is not None:
            pending = {
                "intent_id": source_pending["intent_id"],
                "revision": source_pending["revision"],
                "kind": source_pending["candidate"]["intent"],
                "fields": source_pending["candidate"].get("fields", {}),
            }
        actions = ["send_message"]
        if pending is not None:
            actions.extend(["confirm_pending_intent", "reject_pending_intent"])
        if raw["status"] == "active_hot_work":
            actions.extend(["pause_task", "cancel_task"])
        if raw["status"] == "paused":
            actions.extend(["resume_task", "cancel_task"])
        return {
            "conversation_id": raw["conversation_id"],
            "status": raw["status"],
            "revision": raw["revision"],
            "active_task_id": raw["active_task_id"],
            "pending_intent": pending,
            "messages": visible,
            "task_projection": projection,
            "allowed_actions": actions,
        }

    async def _task_projection(self, identity, raw):
        task_id = raw.get("active_task_id")
        if task_id is None:
            return None
        try:
            result = await self.workflow.read(identity, task_id)
        except (AccessDenied, InvalidTransition, TaskBusy):
            return {
                "task_id": task_id,
                "status": "unavailable",
                "recoverable": True,
                "error": "task_projection_unavailable",
            }
        return result.projection.model_dump(mode="json")

    @staticmethod
    def _state(raw):
        pending = None
        if raw["pending_intent"] is not None:
            value = raw["pending_intent"]
            candidate = value["candidate"]
            pending = PendingIntent(
                intent_id=value["intent_id"],
                kind=candidate["intent"],
                fields=candidate.get("fields", {}),
                revision=value["revision"],
            )
        return ConversationState(
            conversation_id=raw["conversation_id"],
            revision=raw["revision"],
            status=raw["status"],
            active_task_id=raw["active_task_id"],
            pending_intent=pending,
        )

    @staticmethod
    def _context(raw, state, projection):
        return ConversationContext(
            status=state.status,
            messages=[
                VisibleMessage(role=item["role"], text=item["text"])
                for item in raw["messages"]
                if item["role"] in {"user", "assistant", "system_event"}
            ],
            pending_intent=state.pending_intent,
            task_projection=projection,
        )
