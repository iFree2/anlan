"""One scoped perception request; P5 budget identity is a host constant."""

import asyncio
import json

from pydantic import ValidationError

from anlan.infrastructure.budget import CONSOLE_WORK_PACKAGE
from anlan.llm.gateway import ModelGateway
from anlan.workflows.perception_contracts import NOTICE, WORK_PACKAGE, Concern, PerceptionCandidate


def safe_diagnostics(exc):
    """Retain contract locations, never provider-controlled extra field names or values."""
    fields = set(PerceptionCandidate.model_fields) | set(Concern.model_fields)
    diagnostics = []
    for error in exc.errors(include_input=False, include_url=False)[:20]:
        location = [
            part if (isinstance(part, str) and part in fields)
            or (type(part) is int and 0 <= part < 3) else "<extra_field>"
            for part in error["loc"][:5]
        ]
        # Even a schema-known name is untrusted when supplied as an extra field.
        if error["type"] == "extra_forbidden" and location:
            location[-1] = "<extra_field>"
        diagnostics.append({"type": error["type"], "loc": location})
    return diagnostics


class DeepSeekPerceptionModel:
    mode = "deepseek_live"

    def __init__(self, config, client, ledger, *, work_package=WORK_PACKAGE):
        if work_package not in {WORK_PACKAGE, CONSOLE_WORK_PACKAGE}:
            raise ValueError("Perception requires an authorized host package")
        self.gateway = ModelGateway(config, client, ledger, work_package=work_package)
        self._serial = asyncio.Lock()
        self._attempts = {}
        self._diagnostics = {}

    def attempt_for(self, run_id):
        return self._attempts.get(run_id)

    def diagnostics_for(self, run_id):
        return self._diagnostics.get(run_id)

    async def generate(self, context, run_id):
        def parse(envelope):
            try:
                choice = envelope["choices"][0]
                message = choice["message"]
                if (
                    choice["finish_reason"] != "stop"
                    or message["role"] != "assistant"
                    or message.get("tool_calls")
                    or not isinstance(message["content"], str)
                ):
                    raise ValueError("Expected a bounded perception classification")
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                self._diagnostics[run_id] = [{"type": "invalid_envelope", "loc": []}]
                raise
            try:
                return PerceptionCandidate.model_validate_json(message["content"])
            except ValidationError as exc:
                # Field/type metadata only: no HTTP body, input values or provider reasoning.
                self._diagnostics[run_id] = safe_diagnostics(exc)
                raise

        async with self._serial:
            self._diagnostics.pop(run_id, None)
            try:
                candidate, usage, attempt = await self.gateway.call(
                    {
                        "model": self.gateway.config.model,
                        "thinking": {"type": "disabled"},
                        "temperature": 0,
                        "max_tokens": 1024,
                        "response_format": {"type": "json_object"},
                        "messages": context["messages"],
                    },
                    parse,
                    run_id,
                )
            finally:
                self._attempts[run_id] = self.gateway.last_attempt_id
                if self.gateway.last_output_diagnostic:
                    self._diagnostics[run_id] = [
                        {"type": self.gateway.last_output_diagnostic, "loc": []}
                    ]
        return {"candidate": candidate.model_dump(), "usage": usage, "attempt_id": attempt}


class ScriptedPerceptionModel:
    mode = "scripted_double"

    async def generate(self, context, run_id):
        data = json.loads(context["messages"][1]["content"])
        unknown = [o["evidence_id"] for o in data["observations"] if o["outcome"] != "ok"]
        concerns = [{"category": data["event"]["kind"], "evidence_ids": ["e1"]}]
        if unknown:
            concerns.append({"category": "evidence_gap", "evidence_ids": unknown})
        if data["observations"][2]["outcome"] == "ok":
            concerns.append({"category": "context_for_review", "evidence_ids": ["o3"]})
        return {
            "candidate": {
                "event_id": data["event"]["event_id"],
                "concerns": concerns,
                "unknown_observation_ids": unknown,
                "next_steps": ["verify_event_on_site", "review_evidence_with_safety_manager"],
                "notice": NOTICE,
            },
            "attempt_id": None,
            "usage": None,
        }
