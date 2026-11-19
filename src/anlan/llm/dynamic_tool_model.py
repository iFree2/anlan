"""Zero-cost scripted view of one frozen inquiry catalog."""

import json

from anlan.llm.tool_model import FinalAnswer, ModelTurn, ToolCall


class ScriptedDynamicToolModel:
    """Protocol double; does not claim natural language tool selection quality."""

    mode = "scripted_double"

    def __init__(self, catalog=None):
        self.catalog = catalog
        self.tool_schemas = catalog.schemas() if catalog is not None else []

    def bind_catalog(self, catalog):
        # Each run owns its schemas and action state, while the catalog is identical
        # to the Executor's host-frozen catalog.
        return type(self)(catalog)

    async def next(self, messages: list[dict], run_id: str) -> ModelTurn:
        if self.catalog is None:
            raise ValueError("catalog_required")
        observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not observations:
            return ModelTurn(
                calls=[
                    ToolCall(id=f"inquiry_{i}", name=alias, arguments=params)
                    for i, (alias, params) in enumerate(self.catalog.grants)
                ]
            )
        details = []
        citations = []
        for observation in observations:
            capability = observation.get("required_capability", observation["tool"])
            evidence = observation.get("evidence")
            if observation.get("evidence_valid") and evidence:
                citations.append(observation["call_id"])
                remote = evidence["remote"]
                statuses = [record.get("status", "unknown") for record in remote["data"]]
                details.append(
                    f"{capability}: {remote['outcome']}, "
                    f"complete={remote['complete']}, statuses={statuses}, "
                    f"sources={'available' if remote.get('sources') else 'unavailable'}, "
                    f"usable={observation.get('usable', False)}, "
                    f"usability_reason={observation.get('usability_reason')}"
                )
            else:
                details.append(f"{capability}: unknown")
        return ModelTurn(
            final=FinalAnswer(
                summary=(
                    "SYNTHETIC scripted observations; human review required. " + "; ".join(details)
                )[:1000],
                evidence_call_ids=citations,
            )
        )
