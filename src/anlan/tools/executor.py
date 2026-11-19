"""Bounded execution after host authorization; remote data never grants authority."""

import asyncio
import json
from time import perf_counter

from pydantic import AwareDatetime, TypeAdapter

from anlan.tools.policy import TaskCatalog


class ToolExecutionFailure(Exception):
    """Fixed host-measured categories; never accept remote exception text."""

    CODES = frozenset(
        {
            "timeout",
            "disconnected",
            "stale_generation",
            "access_denied",
            "data_error",
            "stale_schema",
            "schema_unsupported",
            "contract_mismatch",
            "oversized_result",
            "tool_budget_exhausted",
            "storage_unavailable",
            "credential_unavailable",
            "cleanup_failed",
            "target_not_allowed",
            "unsupported_target",
            "invalid_configuration",
            "connect_timeout",
            "initialize_failed",
            "discovery_timeout",
            "discovery_incomplete",
        }
    )

    def __init__(self, code):
        self.code = code if code in self.CODES else "data_error"
        super().__init__(self.code)


class ToolExecutor:
    def __init__(self, catalog: TaskCatalog, *, timeout_seconds=5.0, max_result_bytes=65536):
        if not 0 < timeout_seconds <= 5 or not 0 < max_result_bytes <= 65536:
            raise ValueError("invalid execution limits")
        self.catalog = catalog
        self.timeout_seconds = timeout_seconds
        self.max_result_bytes = max_result_bytes

    async def execute(self, name: str, arguments: str) -> dict:
        def failure(reason, executed=False):
            return {
                "tool": name,
                "outcome": "error",
                "reason": reason,
                "facts": None,
                "source": None,
                "executed": executed,
                "evidence_valid": False,
            }

        definition = next((d for d in self.catalog.definitions if d.name == name), None)
        if definition is None:
            return failure("tool_not_allowed")
        try:
            if len(arguments.encode("utf-8")) > 4096:
                raise ValueError("oversized input")
            params = definition.input_model.model_validate_json(arguments).model_dump(mode="json")
        except (ValueError, TypeError, RecursionError):
            return failure("invalid_parameters")
        if params != self.catalog.expected(name):
            return failure("outside_references")
        started = perf_counter()
        try:
            before = TypeAdapter(AwareDatetime).validate_python(definition.clock())
            async with asyncio.timeout(self.timeout_seconds):
                result = await definition.handler(self.catalog.identity, params)
            if perf_counter() - started >= self.timeout_seconds:
                return failure("timeout", True)
            after = TypeAdapter(AwareDatetime).validate_python(definition.clock())
            raw = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            serialized = json.dumps(raw, ensure_ascii=False, allow_nan=False)
            if len(serialized.encode("utf-8")) > self.max_result_bytes:
                raise ValueError("oversized result")
            value = definition.output_model.model_validate_json(serialized)
            when = TypeAdapter(AwareDatetime).validate_python(value.queried_at)
            expected_id = params[definition.object_field] if definition.object_field else None
            if value.tool != name or value.object_id != expected_id or not before <= when <= after:
                raise ValueError("result binding mismatch")
            return {**value.model_dump(mode="json"), "executed": True, "evidence_valid": True}
        except ToolExecutionFailure as exc:
            return failure(exc.code, True)
        except TimeoutError:
            return failure("timeout", True)
        except Exception:
            return failure("data_error", True)
