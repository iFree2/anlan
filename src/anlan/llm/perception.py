"""One scoped perception request; P5 budget identity is a host constant."""

import asyncio
import json

from pydantic import ValidationError

from anlan.llm.gateway import ModelGateway
from anlan.workflows.perception_contracts import NOTICE, WORK_PACKAGE, PerceptionCandidate


class DeepSeekPerceptionModel:
    mode = "deepseek_live"

    def __init__(self, config, client, ledger):
        self.gateway = ModelGateway(config, client, ledger, work_package=WORK_PACKAGE)
        self._serial = asyncio.Lock()
        self._attempts = {}
        self._diagnostics = {}

    def attempt_for(self, run_id):
        return self._attempts.get(run_id)

    def diagnostics_for(self, run_id):
        return self._diagnostics.get(run_id)

    async def generate(self, context, run_id):
        def parse(envelope):
            choice = envelope["choices"][0]
            message = choice["message"]
            if (
                choice["finish_reason"] != "stop"
                or message["role"] != "assistant"
                or message.get("tool_calls")
            ):
                raise ValueError("Expected a bounded perception classification")
            try:
                return PerceptionCandidate.model_validate_json(message["content"])
            except ValidationError as exc:
                # Field/type metadata only: no HTTP body, input values or provider reasoning.
                self._diagnostics[run_id] = [
                    {"type": error["type"], "loc": list(error["loc"])}
                    for error in exc.errors(include_input=False, include_url=False)[:20]
                ]
                raise

        async with self._serial:
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
