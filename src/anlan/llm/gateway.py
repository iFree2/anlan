"""固定供应商HTTP边界：有界输入输出，预占先于请求，无重试。"""

import asyncio
import json

import httpx

from anlan.llm.contracts import AnalysisFailure


class ModelGateway:
    def __init__(self, config, client: httpx.AsyncClient, ledger, *, work_package="P2-WP02"):
        self.config = config
        self.client = client
        self.ledger = ledger
        self.work_package = work_package
        self.requests_used = 0
        self.last_attempt_id = None

    async def call(self, payload: dict, parse, run_id: str):
        self.last_attempt_id = None
        if self.config.model != "deepseek-flash":
            raise AnalysisFailure("model_not_authorized")
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 32768:
            raise AnalysisFailure("input_too_large")
        if self.requests_used >= self.config.max_requests:
            raise AnalysisFailure("budget_exceeded")
        try:
            attempt = await self.ledger.reserve(self.work_package, run_id)
        except Exception as exc:
            category = "budget_exceeded" if type(exc).__name__ == "BudgetExceeded" \
                else "budget_unavailable"
            raise AnalysisFailure(category) from None
        self.last_attempt_id = attempt
        self.requests_used += 1
        usage = None
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with self.client.stream(
                    "POST", "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"},
                    json=payload, timeout=self.config.timeout_seconds,
                ) as response:
                    if response.status_code != 200:
                        category = {429: "model_rate_limited", 401: "model_unauthorized",
                                    403: "model_unauthorized"}.get(
                                        response.status_code, "model_unavailable")
                        raise AnalysisFailure(category)
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            raise AnalysisFailure("invalid_output")
                envelope = json.loads(content)
                raw_usage = envelope.get("usage")
                if isinstance(raw_usage, dict):
                    usage = {name: value if type(value := raw_usage.get(name)) is int
                             and value >= 0 else None for name in (
                                 "prompt_tokens", "completion_tokens", "total_tokens")}
                parsed = parse(envelope)
        except asyncio.CancelledError:
            # 不退款；退出可能发生在供应商已处理之后。reserved仍计入累计。
            raise
        except (TimeoutError, httpx.TimeoutException):
            return await self._failed(attempt, "model_timeout", usage)
        except httpx.HTTPError:
            return await self._failed(attempt, "model_unavailable", usage)
        except AnalysisFailure as exc:
            return await self._failed(attempt, exc.category, usage)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
            return await self._failed(attempt, "invalid_output", usage)
        try:
            await self.ledger.finish(attempt, "succeeded", usage=usage)
        except Exception:
            raise AnalysisFailure("budget_write_failed", usage=usage) from None
        return parsed, usage, attempt

    async def _failed(self, attempt, category, usage):
        try:
            await self.ledger.finish(attempt, "failed", usage=usage, error=category)
        except Exception:
            raise AnalysisFailure("budget_write_failed", usage=usage) from None
        raise AnalysisFailure(category, usage=usage) from None
