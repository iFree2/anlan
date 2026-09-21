"""Single synthesis model adapters; orchestration remains in workflows."""
import json

from anlan.llm.gateway import ModelGateway
from anlan.workflows.review_contracts import WORK_PACKAGE, ReviewCandidate


class DeepSeekReviewModel:
    mode = "deepseek_live"

    def __init__(self, config, client, ledger, *, work_package=WORK_PACKAGE):
        if work_package not in {WORK_PACKAGE, "P4-WP02"}:
            raise ValueError("Unsupported review work package")
        self.gateway = ModelGateway(config, client, ledger, work_package=work_package)

    async def generate(self, context, run_id):
        def parse(envelope):
            choice = envelope["choices"][0]
            message = choice["message"]
            if (choice["finish_reason"] != "stop" or message["role"] != "assistant"
                    or message.get("tool_calls")):
                raise ValueError("Expected a final synthesis")
            return ReviewCandidate.model_validate_json(message["content"])
        candidate, usage, attempt = await self.gateway.call({
            "model": self.gateway.config.model, "thinking": {"type": "disabled"},
            "temperature": 0, "max_tokens": 1024,
            "response_format": {"type": "json_object"}, "messages": context["messages"],
        }, parse, run_id)
        return {"candidate": candidate.model_dump(), "usage": usage, "attempt_id": attempt}

class ScriptedReviewModel:
    """Protocol double using visible observations, not model quality evidence."""
    mode = "scripted_double"

    async def generate(self, context, run_id):
        data = json.loads(context["messages"][1]["content"])
        claims = [{"text": f"SYNTHETIC替身：{o['tool']}={o['outcome']}/{o.get('reason')}",
                   "observation_ids": [o["observation_id"]], "knowledge_citations": []}
                  for o in data["observations"]]
        if data["knowledge"]:
            c = data["knowledge"][0]
            claims.append({"text": c["quote"][:180], "observation_ids": [],
                           "knowledge_citations": [{"chunk_id": c["chunk_id"],
                                                     "quote": c["quote"][:180]}]})
        presentation = {"detail_level": "brief", "presentation_order": "unknowns_first"}
        presentation.update({m["key"]: m["value"] for m in data["preferences"]})
        candidate = ReviewCandidate.model_validate({"claims": claims,
            "unknown_observation_ids": [o["observation_id"] for o in data["observations"]
                                        if o["outcome"] != "ok"],
            "presentation": presentation, "notice": "待人工复核；不是作业批准"})
        return {"candidate": candidate.model_dump(), "usage": None, "attempt_id": None}
