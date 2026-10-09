"""图负责状态转换；节点只返回部分状态更新，不直接修改状态。"""

from time import perf_counter
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from anlan.infrastructure.trace import JsonlTrace
from anlan.llm.contracts import AnalysisFailure
from anlan.workflows.material_analysis import Analysis, Analyzer, missing_issues
from anlan.workflows.material_contracts import Application, Supplement


class TaskState(TypedDict):
    task_id: str
    thread_id: str
    session_id: str
    run_id: str
    correlation_id: str
    fields: dict[str, str]
    revision: int
    status: str
    analysis: dict[str, Any]
    trace_warning: str | None
    analysis_mode: str


def build_graph(analyzer: Analyzer, trace: JsonlTrace, checkpointer=None):
    async def analyze(state: TaskState) -> dict[str, Any]:
        started = perf_counter()
        application = Application.model_validate(state["fields"])
        rules = missing_issues(application)
        try:
            result = await analyzer.analyze(application)
        except AnalysisFailure as exc:
            result = Analysis(semantic_status="failed", error=exc.category, usage=exc.usage,
                              model=exc.model, prompt_version=exc.prompt_version)
        # 确定性的缺字段结论优先于模型给出的候选问题。
        missing = {issue.field for issue in rules}
        result.issues = rules + [issue for issue in result.issues if issue.field not in missing]
        status = "waiting_input" if result.issues else "awaiting_review"
        update = {"analysis": result.model_dump(), "status": status}
        trace_ok = trace.emit(
            "analysis_finished", {**state, **update},
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
            issues=[{"field": i.field, "kind": i.kind, "source": i.source} for i in result.issues],
            semantic_status=result.semantic_status, error=result.error,
            model=result.model, prompt_version=result.prompt_version, usage=result.usage,
        )
        update["trace_warning"] = None if trace_ok else trace.warning
        return update

    def ask(state: TaskState) -> dict[str, Any]:
        # interrupt 之前不做任何 I/O：恢复时这个函数会被从头再次进入。
        response = interrupt({
            "revision": state["revision"], "questions": state["analysis"]["issues"],
        })
        patch = Supplement.model_validate({"fields": response["fields"]})
        application = Application.model_validate({**state["fields"], **patch.fields})
        return {
            "fields": application.model_dump(), "revision": state["revision"] + 1,
            "run_id": response["run_id"], "status": "analyzing",
        }

    graph = StateGraph(TaskState)
    graph.add_node("analyze", analyze)
    graph.add_node("ask", ask)
    graph.add_edge(START, "analyze")
    graph.add_conditional_edges(
        "analyze", lambda state: state["status"],
        {"waiting_input": "ask", "awaiting_review": END},
    )
    graph.add_edge("ask", "analyze")
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
