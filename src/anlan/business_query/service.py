"""Authorized snapshots and deterministic answers; no model or write capability."""

from datetime import UTC, datetime

from pydantic import TypeAdapter

from anlan.business_query.contracts import (
    EvidenceBundle,
    EvidenceCitation,
    EvidenceFact,
    QueryAnswer,
    QueryText,
    QueryType,
)
from anlan.knowledge.tool import UnavailableKnowledgeStore, query_knowledge
from anlan.workflows.material_contracts import LABELS

APPLICATION_LABELS = {"draft": "草稿", "under_review": "安全审核中",
                      "changes_requested": "要求补充", "review_completed": "材料核查完成"}
PROCESS_GUIDANCE = {
    "draft": "补齐材料后可选择安全审核人员并提交。",
    "under_review": "当前等待指定安全审核人员核查，材料已冻结。",
    "changes_requested": "按补充要求更新材料，完成分析后可重新提交。",
    "review_completed": "本轮材料核查已完成；这不代表作业批准或开工授权。",
}
PUBLIC_ACTIONS = {"edit_materials", "submit", "request_changes", "resubmit", "complete_review",
                  "run_event_review", "record_event_feedback"}


class BusinessQueryService:
    def __init__(self, workflow, *, clock=None, knowledge_provider=None, audit=None):
        self.workflow = workflow
        self.clock = clock or (lambda: datetime.now(UTC))
        self.knowledge_provider = knowledge_provider
        self.audit = audit

    async def answer(self, actor, *, query_type: QueryType, question: str,
                     active_task_id: str | None, explicit_task_id: str | None,
                     source_message_id: str | None = None) -> QueryAnswer:
        query_type = TypeAdapter(QueryType).validate_python(query_type)
        TypeAdapter(QueryText).validate_python(question)
        if query_type == "safety_knowledge":
            return await self._answer_knowledge(actor, question)
        target = explicit_task_id or active_task_id
        if target is None:
            return await self._selection_answer(actor)
        result = await self.workflow.read(actor, target)
        try:
            projection = result.projection.model_dump(mode="json")
            bundle = self._application_evidence(query_type, projection)
            return self._compose_application(bundle)
        except (ValueError, KeyError, TypeError, AttributeError):
            return QueryAnswer(text="当前申请数据暂不可查询，请刷新后重试。", outcome="error")

    async def _answer_knowledge(self, actor, question):
        try:
            knowledge = (self.knowledge_provider() if self.knowledge_provider
                         else UnavailableKnowledgeStore(self.clock))
            observation = await query_knowledge(knowledge, actor, {"question": question})
            now = self.clock()
            if observation.outcome != "ok" or not observation.citations:
                outcome = "error" if observation.outcome == "error" else "unknown"
                limitation = ("knowledge_unavailable" if outcome == "error"
                              else "no_eligible_evidence")
                return self._knowledge_failure(outcome, limitation, now)
            citations = [EvidenceCitation.model_validate({k: item[k]
                         for k in EvidenceCitation.model_fields})
                         for item in observation.citations[:3]]
            if any(not (c.valid_from <= now < c.valid_until) for c in citations):
                return self._knowledge_failure("unknown", "expired_citation", now)
            bundle = EvidenceBundle(query_type="safety_knowledge", observed_at=now,
                                    citations=citations)
            primary = citations[0]
            text = (f"根据《{primary.title}》的当前可用依据：{primary.quote}"
                    f"（引用 {primary.doc_id}/{primary.chunk_id}，来源 {primary.source}）。"
                    "该说明用于材料准备，不代表作业批准或开工授权。"
                    f"查询时间 {now.isoformat()}。")
            return QueryAnswer(text=text, evidence=bundle, outcome="ok")
        except Exception:
            return self._knowledge_failure("error", "knowledge_unavailable", self.clock())

    @staticmethod
    def _knowledge_failure(outcome, limitation, now):
        text = ("知识服务暂不可查询，请稍后重试。" if outcome == "error"
                else "当前知识库没有足够依据回答这个问题。")
        return QueryAnswer(text=text, outcome=outcome, evidence=EvidenceBundle(
            query_type="safety_knowledge", observed_at=now, limitations=[limitation]))

    async def _selection_answer(self, actor):
        items = await self.workflow.applications(actor)
        # Reapply the summary whitelist even to a custom adapter.
        summaries = [{k: v for k, v in item.items()
                      if k in {"task_id", "status", "version", "updated_at"}}
                     for item in items[:20]]
        if not summaries:
            return QueryAnswer(text="暂无可查询申请。请通过现有入口创建或选择获授权的申请。",
                               outcome="unknown")
        identifiers = "、".join(str(item["task_id"]) for item in summaries)
        return QueryAnswer(text=f"请选择要查询的申请：{identifiers}。查询不会自动绑定申请。",
                           requires_selection=True, candidate_tasks=summaries,
                           outcome="selection_required")

    def _application_evidence(self, query_type, projection):
        shared = projection["collaboration"]
        application = shared["application"]
        status = application["status"]
        if status not in APPLICATION_LABELS:
            raise ValueError("unknown state")
        fields = projection["fields"]
        missing = projection["missing_fields"]
        if any(key not in LABELS for key in (*fields, *missing)):
            raise ValueError("unknown field")
        facts = [
            EvidenceFact(key="application_status", value=status,
                         source="collaboration_application"),
            EvidenceFact(key="material_status", value=projection["status"],
                         source="material_checkpoint"),
            EvidenceFact(key="missing_fields", value=missing, source="material_checkpoint"),
            EvidenceFact(key="current_handler", value=("safety_manager" if status == "under_review"
                         else "none" if status == "review_completed" else "applicant"),
                         source="collaboration_policy"),
        ]
        if query_type == "application_details":
            facts.append(EvidenceFact(key="fields", value={k: fields[k] for k in LABELS
                                                          if k in fields},
                                      source="material_checkpoint"))
        if query_type == "process_guidance":
            facts.append(EvidenceFact(key="next_step", value=PROCESS_GUIDANCE[status],
                                      source="collaboration_policy"))
        return EvidenceBundle(query_type=query_type, task_id=projection["task_id"],
                              material_revision=projection["revision"],
                              application_version=application["version"], observed_at=self.clock(),
                              facts=facts, allowed_actions=[a for a in shared["allowed_actions"]
                                                          if a in PUBLIC_ACTIONS])

    @staticmethod
    def _compose_application(bundle):
        facts = {fact.key: fact.value for fact in bundle.facts}
        status = facts["application_status"]
        text = f"申请 {bundle.task_id} 当前为“{APPLICATION_LABELS[status]}”。"
        missing = "、".join(LABELS[k] for k in facts["missing_fields"])
        text += f"缺失材料：{missing}。" if missing else "必填材料已填写。"
        if bundle.query_type == "application_details":
            text += "；".join(f"{LABELS[k]}：{v}" for k, v in facts["fields"].items()) + "。"
        if bundle.query_type == "process_guidance":
            text += facts["next_step"]
        text += (f" 材料版本 {bundle.material_revision}，申请版本 {bundle.application_version}，"
                 f"查询时间 {bundle.observed_at.isoformat()}。")
        return QueryAnswer(text=text, evidence=bundle, outcome="ok")
