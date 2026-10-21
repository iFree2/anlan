from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_console import config
from test_events_postgres import dsn, run  # noqa: F401

from anlan.infrastructure.budget import BudgetLedger
from anlan.interfaces.service_config import ServiceConfig
from anlan.interfaces.service_models import ServiceModels
from anlan.llm.config import ModelConfig


def test_release_package_is_trusted_configuration_and_defaults_to_existing_package():
    assert config().console_work_package == "P8-WP04"
    configured = ServiceConfig.model_validate(
        config().model_dump() | {"console_work_package": "P11-WP02"}
    )
    assert configured.console_work_package == "P11-WP02"
    with pytest.raises(ValidationError):
        ServiceConfig.model_validate(
            config().model_dump() | {"console_work_package": "unbounded-new-package"}
        )


def test_material_and_event_models_use_configured_release_package():
    configured = ServiceConfig.model_validate(config().model_dump() | {
        "model_mode": "deepseek_live", "console_work_package": "P11-WP02",
    })
    models = ServiceModels("unused", configured, lambda: None,
                           model_config=ModelConfig(api_key="test-only"))
    with patch("anlan.interfaces.service_models.DeepSeekAnalyzer") as analyzer:
        models.material_service()
        assert analyzer.call_args.kwargs["work_package"] == "P11-WP02"
    assert models.perception().gateway.work_package == "P11-WP02"


@pytest.mark.postgres
def test_release_migration_preserves_existing_attempts_and_limits(dsn):  # noqa: F811
    async def scenario():
        ledger = BudgetLedger(dsn, "test-release-" + uuid4().hex)
        await ledger.initialize()
        await ledger.reserve("P8-WP04", "old-release")
        before = await ledger.snapshot()
        await ledger.reserve("P11-WP02", "conversation-release")
        await ledger.initialize()
        after = await ledger.snapshot()
        assert after["attempts"][0] == before["attempts"][0]
        assert after["total_limit"] == before["total_limit"] == 100
        assert after["package_limit"] == before["package_limit"] == 10
        assert after["packages"] == {"P8-WP04": 1, "P11-WP02": 1}
    run(scenario())
