import asyncio
from uuid import uuid4

import pytest
from test_events import OWNER
from test_events_postgres import dsn, run  # noqa: F401

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.infrastructure.conversations import ConversationStore

pytestmark = pytest.mark.postgres


def request_id(prefix):
    return f"{prefix}-{uuid4().hex}"


def test_message_reservation_is_idempotent_and_rejects_changed_payload(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        await store.initialize()
        conversation = await store.create(OWNER, request_id=request_id("create"))
        first = await store.reserve_message(
            OWNER, conversation["conversation_id"], "message-1", 1, "我要申请动火"
        )
        replay = await store.reserve_message(
            OWNER, conversation["conversation_id"], "message-1", 1, "我要申请动火"
        )
        assert replay == first
        with pytest.raises(InvalidTransition):
            await store.reserve_message(
                OWNER, conversation["conversation_id"], "message-1", 1, "changed"
            )

    run(scenario())


def test_other_identity_cannot_observe_conversation(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("private"))
        other = OWNER.model_copy(update={"user_id": "other"})
        with pytest.raises(AccessDenied):
            await store.get(other, conversation["conversation_id"])
        assert all(
            row["conversation_id"] != conversation["conversation_id"]
            for row in await store.list(other)
        )

    run(scenario())


def test_create_replay_and_restart_restore_the_same_conversation(dsn):  # noqa: F811
    async def scenario():
        create_request = request_id("restart")
        first_store = ConversationStore(dsn)
        conversation = await first_store.create(OWNER, request_id=create_request)
        replay = await ConversationStore(dsn).create(OWNER, request_id=create_request)
        restored = await ConversationStore(dsn).get(OWNER, conversation["conversation_id"])
        assert replay == conversation
        assert restored == conversation

    run(scenario())


def test_messages_have_monotonic_order_and_survive_restart(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("ordered"))
        first = await store.reserve_message(
            OWNER, conversation["conversation_id"], "ordered-1", 1, "第一条"
        )
        first_result = {"status": "assistant_completed", "text": "已收到第一条"}
        assert await store.finish_message(
            OWNER,
            conversation["conversation_id"],
            first["message_id"],
            first_result,
        ) == first_result
        second = await store.reserve_message(
            OWNER, conversation["conversation_id"], "ordered-2", 2, "第二条"
        )
        await store.finish_message(
            OWNER,
            conversation["conversation_id"],
            second["message_id"],
            {"status": "assistant_completed", "text": "已收到第二条"},
        )

        restored = await ConversationStore(dsn).get(OWNER, conversation["conversation_id"])
        assert [message["text"] for message in restored["messages"]] == ["第一条", "第二条"]
        assert [message["ordinal"] for message in restored["messages"]] == sorted(
            message["ordinal"] for message in restored["messages"]
        )
        assert all(message["status"] == "completed" for message in restored["messages"])

    run(scenario())


def test_stale_revision_and_second_pending_message_are_rejected(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("guard"))
        await store.reserve_message(
            OWNER, conversation["conversation_id"], "pending-1", 1, "尚未完成"
        )
        with pytest.raises(InvalidTransition, match="revision"):
            await store.reserve_message(
                OWNER, conversation["conversation_id"], "stale", 1, "旧版本"
            )
        with pytest.raises(TaskBusy):
            await store.reserve_message(
                OWNER, conversation["conversation_id"], "pending-2", 2, "并发消息"
            )

    run(scenario())


def test_route_pending_intent_and_task_binding_are_durable(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("route"))
        message = await store.reserve_message(
            OWNER, conversation["conversation_id"], "candidate-1", 1, "V101 管线补焊"
        )
        proposal = {
            "intent": "hot_work_candidate",
            "fields": {"work_object_description": "V101 管线补焊"},
            "requires_confirmation": True,
            "user_explanation": "检测到动火候选",
            "classifier_version": "scripted-intent-v1",
        }
        decision = {
            "action": "ask_confirmation",
            "fields": proposal["fields"],
            "active_task_id": None,
            "business_write": False,
        }
        await store.save_route(
            OWNER, conversation["conversation_id"], message["message_id"], proposal, decision
        )
        pending = await store.set_pending_intent(
            OWNER, conversation["conversation_id"], message["message_id"], proposal
        )
        await store.finish_message(
            OWNER,
            conversation["conversation_id"],
            message["message_id"],
            {"status": "intent_confirmation_required"},
        )

        restored = await ConversationStore(dsn).get(OWNER, conversation["conversation_id"])
        assert restored["status"] == "pending_confirmation"
        assert restored["pending_intent"]["intent_id"] == pending["intent_id"]
        assert restored["pending_intent"]["candidate"] == proposal
        assert restored["routes"][0]["proposal"] == proposal
        assert restored["routes"][0]["decision"] == decision

        bound = await store.bind_task(
            OWNER, conversation["conversation_id"], restored["revision"], "task-1"
        )
        assert bound["status"] == "active_hot_work"
        assert bound["active_task_id"] == "task-1"
        assert bound["pending_intent"] is None

    run(scenario())


def test_amended_candidate_preserves_immutable_intent_revisions(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("amend"))
        first_message = await store.reserve_message(
            OWNER, conversation["conversation_id"], "amend-1", 1, "V101 补焊"
        )
        first = await store.set_pending_intent(
            OWNER,
            conversation["conversation_id"],
            first_message["message_id"],
            {"intent": "hot_work_candidate", "fields": {"work_object_description": "V101"}},
        )
        await store.finish_message(
            OWNER, conversation["conversation_id"], first_message["message_id"], {"ok": True}
        )
        second_message = await store.reserve_message(
            OWNER, conversation["conversation_id"], "amend-2", 2, "改成 V202"
        )
        second = await store.set_pending_intent(
            OWNER,
            conversation["conversation_id"],
            second_message["message_id"],
            {"intent": "hot_work_candidate", "fields": {"work_object_description": "V202"}},
        )
        assert second["revision"] == first["revision"] + 1
        assert second["intent_id"] != first["intent_id"]
        assert (await store.get(OWNER, conversation["conversation_id"]))["pending_intent"][
            "candidate"
        ]["fields"] == {"work_object_description": "V202"}

    run(scenario())


def test_failed_message_releases_the_active_writer_slot(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("failed"))
        first = await store.reserve_message(
            OWNER, conversation["conversation_id"], "failure-1", 1, "会失败"
        )
        failed = await store.fail_message(
            OWNER, conversation["conversation_id"], first["message_id"], "classifier_failure"
        )
        assert failed == {"error_category": "classifier_failure"}
        second = await store.reserve_message(
            OWNER, conversation["conversation_id"], "failure-2", 2, "重试"
        )
        assert second["status"] == "pending"

    run(scenario())


def test_only_one_process_can_hold_the_conversation_operation_lock(dsn):  # noqa: F811
    async def scenario():
        first = ConversationStore(dsn)
        second = ConversationStore(dsn)
        conversation = await first.create(OWNER, request_id=request_id("lock"))
        message = await first.reserve_message(
            OWNER, conversation["conversation_id"], "lock-message", 1, "等待处理"
        )
        async with first.operation_lock(
            OWNER, conversation["conversation_id"], message["message_id"]
        ):
            with pytest.raises(TaskBusy):
                async with second.operation_lock(
                    OWNER, conversation["conversation_id"], message["message_id"]
                ):
                    pytest.fail("a second writer acquired the same conversation lock")
        async with second.operation_lock(
            OWNER, conversation["conversation_id"], message["message_id"]
        ):
            pass

    run(scenario())


def test_concurrent_reservations_leave_exactly_one_pending_message(dsn):  # noqa: F811
    async def scenario():
        store = ConversationStore(dsn)
        conversation = await store.create(OWNER, request_id=request_id("race"))

        async def reserve(number):
            try:
                return await ConversationStore(dsn).reserve_message(
                    OWNER,
                    conversation["conversation_id"],
                    f"race-{number}",
                    1,
                    f"消息 {number}",
                )
            except (InvalidTransition, TaskBusy) as exc:
                return exc

        outcomes = await asyncio.gather(reserve(1), reserve(2))
        assert sum(isinstance(item, dict) for item in outcomes) == 1
        assert sum(isinstance(item, (InvalidTransition, TaskBusy)) for item in outcomes) == 1

    run(scenario())
