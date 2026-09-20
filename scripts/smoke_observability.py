"""实际三工具/本地编码/PG运行并查询Jaeger；知识故障注入明确标注。"""

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import httpx

from anlan.analysis import OfflineAnalyzer
from anlan.cli import DEMO_FIELDS
from anlan.contracts import Identity
from anlan.embeddings import LocalEmbeddings
from anlan.knowledge import KnowledgeStore
from anlan.knowledge_tool import UnavailableKnowledgeStore
from anlan.postgres import database_url
from anlan.service import WorkflowService
from anlan.telemetry import root_span_id, trace_id
from anlan.tool_loop import check_facts_agent
from anlan.tool_model import ScriptedToolModel
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace


class ScenarioTrace(JsonlTrace):
    def __init__(self, path, scenario):
        super().__init__(path)
        self.scenario = scenario

    def emit(self, event, state, **details):
        return super().emit(event, state, scenario=self.scenario, **details)


def require(condition, category):
    if not condition:
        raise ValueError(category)


async def evaluate(args):
    if not os.environ.get("ANLAN_OTLP_ENDPOINT"):
        raise ValueError("Load dev-jaeger.ps1 -Action Env first")
    source = json.loads(args.source_report.read_text(encoding="utf-8-sig"))
    identity = Identity(tenant_id=source["tenant_id"], user_id="safety-manager-demo")

    def clock():
        return datetime.fromisoformat("2026-09-20T12:00:00Z")

    report = {
        "status": "failed",
        "data_origin": "SYNTHETIC",
        "requests_this_run": 0,
        "model_mode": "scripted_double",
        "platform": "Jaeger 2.21.0",
        "runs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        try:
            knowledge = KnowledgeStore(database_url(), await LocalEmbeddings.create(), clock=clock)
            async with httpx.AsyncClient(
                timeout=2, trust_env=False, follow_redirects=False
            ) as client:
                services = await client.get("http://127.0.0.1:16686/api/v3/services")
                services.raise_for_status()
                for label, store in [
                    ("actual_synthetic_lookup", knowledge),
                    ("knowledge_error_injected", UnavailableKnowledgeStore(clock)),
                ]:
                    trace = ScenarioTrace(args.output.with_suffix(".trace.jsonl"), label)
                    service = WorkflowService(OfflineAnalyzer(), trace)
                    state = await service.start(identity, DEMO_FIELDS)
                    evidence = await check_facts_agent(
                        service,
                        identity,
                        state["task_id"],
                        {
                            "worker_id": "worker-001",
                            "qualification_type": "welding",
                            "area_id": "area-001",
                        },
                        FactTools(args.source_report.with_suffix(".facts"), clock=clock),
                        ScriptedToolModel(),
                        trace,
                        knowledge_store=store,
                        knowledge_question="动火现场需要怎样安排监护人员？",
                    )
                    ident = trace_id(evidence["run_id"])
                    result = None
                    for _ in range(30):
                        response = await client.get("http://127.0.0.1:16686/api/traces/" + ident)
                        if response.status_code == 200:
                            data = response.json().get("data", [])
                            if data and len(data[0].get("spans", [])) >= 6:
                                result = data[0]
                                break
                        await asyncio.sleep(0.2)
                    entry = {
                        "scenario": label,
                        "trace_id": ident,
                        "evidence": evidence,
                        "jaeger_trace": result,
                        "material_unchanged": await service.get(identity, state["task_id"])
                        == state,
                    }
                    report["runs"].append(entry)
                    require(result is not None, "trace_not_queryable")
                    spans = result["spans"]
                    root_id = root_span_id(evidence["run_id"])
                    require(sum(span["spanID"] == root_id for span in spans) == 1, "invalid_root")
                    require(
                        all(
                            any(ref["spanID"] == root_id for ref in span.get("references", []))
                            for span in spans
                            if span["spanID"] != root_id
                        ),
                        "invalid_parent",
                    )
                    tool = next(s for s in spans if s["operationName"] == "tool.query_knowledge")
                    tags = {t["key"]: t["value"] for t in tool["tags"]}
                    require(tags["anlan.scenario"] == label, "invalid_scenario")
                    if label == "knowledge_error_injected":
                        require(tags["anlan.reason"] == "knowledge_unavailable", "missing_error")
                        require(tags.get("error") is True, "missing_error_flag")
                    else:
                        sources = json.loads(tags["anlan.sources"])
                        require(
                            any(s["doc_id"] == "watcher" and s["chunk_id"] for s in sources),
                            "missing_knowledge_source",
                        )
                    require(evidence["trace_warning"] is None, "trace_gap")
                    require(entry["material_unchanged"], "material_mutated")
                report["status"] = "passed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {"status": report["status"], "traces": len(report["runs"]), "output": str(args.output)}
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(args), loop_factory=asyncio.SelectorEventLoop))
