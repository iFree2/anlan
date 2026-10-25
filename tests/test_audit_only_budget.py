"""Unlimited project calls retain durable reservations and existing audit history."""
import asyncio
from uuid import uuid4

import pytest
from test_console import config
from test_events_postgres import dsn, run  # noqa: F401 -- actual loopback PG

from anlan.infrastructure.budget import BudgetExceeded, BudgetLedger
from anlan.interfaces.service_config import ServiceConfig
from anlan.interfaces.service_models import ServiceModels
from anlan.llm.config import ModelConfig

pytestmark = pytest.mark.postgres


async def audit_only(ledger):
    async with await ledger._connect() as conn:
        # Administrative test setup, never an HTTP capability.
        await conn.execute('INSERT INTO anlan_v2.model_call_policies '
            '(authorization_id,limits_enforced,reason) VALUES (%s,false,%s)',
            (ledger.authorization_id, 'Explicit isolated test authorization'))


def test_exhausted_calls_continue_with_audit_after_explicit_policy_without_reset(dsn):  # noqa: F811
    async def scenario():
        ledger = BudgetLedger(dsn, 'test-audit-only-' + uuid4().hex, 1, 1)
        await ledger.initialize()
        first = await ledger.reserve('P11-WP01', 'prior-failure')
        await ledger.finish(first, 'failed', error='invalid_output')
        before = await ledger.snapshot()
        with pytest.raises(BudgetExceeded):
            await ledger.reserve('P11-WP01', 'blocked-before-authorization')
        await audit_only(ledger)
        attempts = await asyncio.gather(*[
            ledger.reserve('P11-WP01', 'same-run') for _ in range(12)])
        assert len(set(attempts)) == 12
        fresh = BudgetLedger(dsn, ledger.authorization_id, 1, 1)
        await fresh.initialize()
        after = await fresh.snapshot()
        assert after['limits_enforced'] is False
        assert after['total_limit'] == after['package_limit'] == 1  # Historical settings.
        assert after['total_reserved'] == 13
        assert after['packages'] == {'P11-WP01': 13}
        assert after['attempts'][0] == before['attempts'][0]
        assert after['status_counts'] == {'reserved': 12, 'failed': 1, 'succeeded': 0}
        await fresh.finish(attempts[0], 'succeeded', usage={'total_tokens': 1})
        assert (await fresh.snapshot())['total_reserved'] == 13
    run(scenario())


def test_default_policy_remains_limited_and_cannot_be_changed_through_client_config(dsn):  # noqa: F811
    async def scenario():
        ledger = BudgetLedger(dsn, 'test-default-policy-' + uuid4().hex, 1, 1)
        await ledger.initialize()
        assert (await ledger.snapshot())['limits_enforced'] is True
        await ledger.reserve('P11-WP02', 'first')
        with pytest.raises(BudgetExceeded):
            await ledger.reserve('P11-WP02', 'second')
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ServiceConfig.model_validate(config().model_dump() | {'limits_enforced': False})
    run(scenario())


def test_audit_only_public_info_has_no_effective_limits_but_keeps_used_counts(dsn):  # noqa: F811
    async def scenario():
        ledger = BudgetLedger(dsn, 'test-info-policy-' + uuid4().hex, 1, 1)
        await ledger.initialize()
        await audit_only(ledger)
        await ledger.reserve('P11-WP01', 'one')
        await ledger.reserve('P11-WP02', 'two')
        configured = ServiceConfig.model_validate(config().model_dump() | {
            'model_mode': 'deepseek_live', 'console_work_package': 'P11-WP02'})
        models = ServiceModels(dsn, configured, lambda: None, ledger=ledger,
                               model_config=ModelConfig(api_key='test-only-not-a-live-key'))
        info = await models.public_info()
        assert info['budget']['status'] == 'audit_only'
        assert info['budget']['total_used'] == 2
        for value in (info['budget'], info['conversation_budget']):
            assert value['limits_enforced'] is False
            assert value['package_limit'] is None
            assert value['package_remaining'] is None
            assert value['package_used'] == 1
        assert info['budget']['total_limit'] is None
    run(scenario())
