"""Graph owns state transitions; nodes return partial updates, not mutated state."""

from time import perf_counter
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from anlan.analysis import Analysis, AnalysisFailure, Analyzer, missing_issues
from anlan.contracts import Application, Supplement
from anlan.trace import JsonlTrace


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


def build_graph(analyzer: Analyzer, trace: JsonlTrace):
    async def analyze(state: TaskState) -> dict[str, Any]:
        started = perf_counter()
        application = Application.model_validate(state["fields"])
        rules = missing_issues(application)
        try:
            result = await analyzer.analyze(application)
        except AnalysisFailure as exc:
            result = Analysis(semantic_status="failed", error=exc.category, usage=exc.usage,
                              model=exc.model, prompt_version=exc.prompt_version)
        # Deterministic missing-field findings take precedence over semantic candidates.
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
        update["trace_warning"] = None if trace_ok else "trace_write_failed"
        return update

    def ask(state: TaskState) -> dict[str, Any]:
        # No I/O before interrupt: this function is entered again on resume.
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
    return graph.compile(checkpointer=InMemorySaver())
