"""Read-only preflight executor; it deliberately contains no model synthesis."""

import asyncio
from datetime import UTC, datetime

from anlan.knowledge.tool import query_knowledge
from anlan.preflight.evaluator import evaluate


class PreflightRunner:
    def __init__(self, facts, knowledge, *, clock=None):
        self.facts, self.knowledge = facts, knowledge
        self.clock = clock or (lambda: datetime.now(UTC))

    async def run(self, actor, references, materials):
        started_at = self.clock()
        async def facts():
            worker = await self.facts.query_worker_qualification(
                actor,
                {
                    "worker_id": references["worker_id"],
                    "qualification_type": references["qualification_type"],
                },
            )
            area = await self.facts.query_area_status(actor, {"area_id": references["area_id"]})
            return tuple(
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in (worker, area)
            )

        method = materials.get("work_method_description", materials.get("work_method", ""))
        target = materials.get("work_object_description", materials.get("work_object", ""))
        question = (
            f"{method[:80]} {target[:80]} 作业人员 {references['worker_id']} "
            f"资质 {references['qualification_type']} 区域 {references['area_id']} 适用安全规程"
        )
        (worker, area), observation = await asyncio.gather(
            facts(), query_knowledge(self.knowledge, actor, {"question": question[:500]})
        )
        knowledge = observation.model_dump(mode="json")
        assessment = evaluate(worker, area, knowledge, started_at)
        return {
            "ready": assessment.ready,
            "valid_until": assessment.valid_until.isoformat(),
            "citation_ids": assessment.citation_ids,
            "issues": assessment.issues,
            "worker": worker,
            "area": area,
            "knowledge": knowledge,
            "question": question[:500],
            "queried_at": started_at.isoformat(),
            "rules_version": "preflight-v1",
        }
