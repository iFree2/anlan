"""在已授权材料快照上执行固定只读核验；不改动图状态或提交历史。"""

from uuid import uuid4

from anlan.contracts import Identity
from anlan.service import WorkflowService
from anlan.tools.contracts import FactReferences
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace


async def check_facts(service: WorkflowService, identity: Identity, task_id: str,
                      references: dict, tools: FactTools, trace: JsonlTrace) -> dict:
    snapshot = await service.get(identity, task_id)
    refs = FactReferences.model_validate(references)
    report = {
        "schema_version": "fact-evidence-v1", "data_origin": "SYNTHETIC",
        "mode": "fixed_read_only_tools", "requests_this_run": 0,
        "notice": "合成事实证据需人工复核，不是作业批准；仅对应所列材料版本。",
        "task_id": snapshot["task_id"], "correlation_id": snapshot["correlation_id"],
        "revision": snapshot["revision"], "source_run_id": snapshot["run_id"],
        "source_material_status": snapshot["status"], "run_id": str(uuid4()),
        "status": "awaiting_review", "trace_warning": None, "results": [],
    }
    queries = [
        (tools.query_worker_qualification,
         {"worker_id": refs.worker_id, "qualification_type": refs.qualification_type}),
        (tools.query_area_status, {"area_id": refs.area_id}),
    ]
    for query, parameters in queries:
        result = await query(identity, parameters)
        report["results"].append(result.model_dump(mode="json"))
        if not trace.emit(
            "tool_finished", report, source_run_id=report["source_run_id"],
            tool=result.tool, object_id=result.object_id, queried_at=result.queried_at.isoformat(),
            outcome=result.outcome, reason=result.reason, elapsed_ms=result.elapsed_ms,
            source=result.source.model_dump(mode="json") if result.source else None,
        ):
            report["trace_warning"] = "trace_write_failed"
    return report
