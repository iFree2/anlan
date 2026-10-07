"""Server-owned model composition; credentials and budget never come from HTTP."""
from contextlib import asynccontextmanager

import httpx

from anlan.infrastructure.budget import CONSOLE_WORK_PACKAGE, BudgetLedger
from anlan.interfaces.runtime import postgres_service
from anlan.llm.config import ModelConfig
from anlan.llm.material import DeepSeekAnalyzer
from anlan.llm.perception import DeepSeekPerceptionModel
from anlan.workflows.material_analysis import OfflineAnalyzer


class ServiceModels:
    def __init__(self, dsn, config, model_factory, *, model_config=None,
                 transport=None, ledger=None):
        self.dsn = dsn
        self.live = config.model_mode == "deepseek_live"
        self.material_mode = "deepseek_live" if self.live else "offline"
        self.model_mode = config.model_mode
        self.config = (model_config or ModelConfig.from_env()) if self.live else None
        if self.live and self.config.model != "deepseek-flash":
            raise ValueError("Online console requires the authorized DeepSeek model")
        self.ledger = ledger if ledger is not None else BudgetLedger(dsn)
        self.transport, self.model_factory, self.client = transport, model_factory, None

    @asynccontextmanager
    async def lifespan(self):
        if not self.live:
            yield
            return
        async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                                     follow_redirects=False) as client:
            self.client = client
            try:
                yield
            finally:
                self.client = None

    def material_service(self):
        analyzer = (DeepSeekAnalyzer(self.config, self.client, ledger=self.ledger,
                                    work_package=CONSOLE_WORK_PACKAGE)
                    if self.live else OfflineAnalyzer())
        return postgres_service(self.dsn, analyzer, mode=self.material_mode)

    def perception(self):
        if self.live:
            return DeepSeekPerceptionModel(self.config, self.client, self.ledger,
                                           work_package=CONSOLE_WORK_PACKAGE)
        return self.model_factory()

    async def public_info(self):
        value = {"material_mode": self.material_mode, "model_mode": self.model_mode,
                 "model": self.config.model if self.live else None}
        if self.live:
            try:
                budget = await self.ledger.snapshot()
                used = budget["packages"].get(CONSOLE_WORK_PACKAGE, 0)
                value["budget"] = {
                    "status": "available", "work_package": CONSOLE_WORK_PACKAGE,
                    "total_used": budget["total_reserved"], "total_limit": budget["total_limit"],
                    "package_used": used, "package_limit": budget["package_limit"],
                    "package_remaining": min(budget["package_limit"] - used,
                                             budget["total_limit"] - budget["total_reserved"]),
                }
            except Exception:
                value["budget"] = {"status": "unavailable", "package_remaining": 0}
        return value
