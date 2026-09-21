"""冻结P2工程回归：真实图/工具/本地向量/PG/Jaeger，模型用明确替身。"""

import argparse
import asyncio
import copy
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.infrastructure.telemetry import root_span_id, trace_id
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.knowledge.contracts import KnowledgeCitation
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.knowledge.tool import UnavailableKnowledgeStore
from anlan.llm.tool_model import ScriptedToolModel
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService
from anlan.workflows.tool_loop import check_facts_agent

ROOT = Path(__file__).resolve().parents[1]


def read_inputs():
    manifest = json.loads((ROOT / "evals/phase02-regression-v1/manifest.json").read_text("utf-8"))
    inputs = {}
    for name, entry in manifest["files"].items():
        raw = json.loads((ROOT / entry["path"]).read_text(encoding="utf-8-sig"))
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if hashlib.sha256(canonical.encode()).hexdigest() != entry["sha256"]:
            raise ValueError("frozen input checksum mismatch: " + name)
        inputs[name] = raw
    return manifest, inputs


def check_result(evidence, expected, before, after):
    return (
        before == after
        and [[r["outcome"], r["reason"]] for r in evidence["results"]] == expected["outcomes"]
        and evidence["stop_reason"] == expected["stop"]
        and 1 <= evidence["model_steps"] <= 3
        and evidence["tool_calls"] == len(expected["outcomes"]) <= 4
        and evidence["trace_warning"] == expected.get("trace_warning")
    )


def check_embedding(actual, expected):
    if actual["artifact_sha256"] != expected["artifact_sha256"]:
        raise ValueError("frozen embedding artifact mismatch")


def check_budget(before, current, historical):
    initial_ids = {a["attempt_id"] for a in before["attempts"]}
    actual = {a["attempt_id"]: a for a in current["attempts"]}
    new = set(actual) - initial_ids
    removed = initial_ids - set(actual)
    return {
        "initial_total": before["total_reserved"],
        "current_total": current["total_reserved"],
        "historical_attempts": len(historical),
        "new_reservations": len(new),
        "removed_reservations": len(removed),
        "passed": not new
        and not removed
        and current["total_reserved"] == before["total_reserved"] == len(actual) <= 100
        and all(n <= 10 for n in current["packages"].values())
        and all(
            a["attempt_id"] in actual
            and all(
                actual[a["attempt_id"]][k] == a[k]
                for k in ("work_package", "run_id", "status", "usage")
            )
            for a in historical
        ),
    }


class GateModel(ScriptedToolModel):
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = 0

    async def next(self, messages, run_id):
        self.calls += 1
        turn = await super().next(messages, run_id)
        if self.scenario == "p2-05-identity-injection" and turn.calls:
            parameters = json.loads(turn.calls[0].arguments)
            turn.calls[0].arguments = json.dumps({**parameters, "tenant_id": "other"})
        if self.scenario == "p2-06-fabricated-quote" and turn.final:
            turn.final.knowledge_citations = [
                KnowledgeCitation(chunk_id="fabricated", quote="不存在的原文")
            ]
        return turn


class UnavailableExporter:
    def export(self, record):
        return False


async def withdrawal_probe(knowledge, owner, template):
    # 此场景只撤回自有临时文档，不能改变后续场景共享的watcher语料。
    document = {
        **template,
        "doc_id": "gate-withdrawal",
        "source": "synthetic-regression/gate-withdrawal",
    }
    await knowledge.ingest(owner, document)
    other = Identity(tenant_id=owner.tenant_id, user_id="other-user")
    try:
        await knowledge.withdraw(other, document["doc_id"])
    except AccessDenied:
        pass
    else:
        return False
    before = await knowledge.search(owner, {"question": "监护人员如何安排？"})
    await knowledge.withdraw(owner, document["doc_id"])
    after = await knowledge.search(owner, {"question": "监护人员如何安排？"})
    return any(c["doc_id"] == document["doc_id"] for c in before["citations"]) and all(
        c["doc_id"] != document["doc_id"] for c in after["citations"]
    )


async def platform_check(run_id):
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        for _ in range(25):
            response = await client.get("http://127.0.0.1:16686/api/traces/" + trace_id(run_id))
            if response.status_code == 200:
                traces = response.json().get("data", [])
                if traces and len(traces[0].get("spans", [])) == 6:
                    spans = traces[0]["spans"]
                    root = root_span_id(run_id)
                    return {
                        "trace_id": trace_id(run_id),
                        "span_count": len(spans),
                        "passed": sum(s["spanID"] == root for s in spans) == 1
                        and all(
                            any(ref["spanID"] == root for ref in s.get("references", []))
                            for s in spans
                            if s["spanID"] != root
                        )
                        and any(
                            s["operationName"] == "tool.query_knowledge"
                            and any(t["key"] == "anlan.sources" for t in s["tags"])
                            for s in spans
                        ),
                    }
            await asyncio.sleep(0.2)
    return {"passed": False, "error": "trace_not_found"}


async def run(args):
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "engineering_status": "failed",
        "suite_version": "phase02-regression-v1",
        "model_requests_this_run": 0,
        "model_mode": "scripted_double",
        "encoding": "real_local_neural",
        "model_generalization": "not_validated",
        "learner_mastery": "not_validated",
        "summary_completeness": "known_uncited_secondary_claim_in_wp04",
        "results": [],
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:

        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        save()
        try:
            manifest, inputs = read_inputs()
            report["frozen_files"] = manifest["files"]
            suite = inputs["cases"]
            if not os.environ.get("ANLAN_OTLP_ENDPOINT"):
                raise ValueError("Jaeger environment required")
            budget_before = await BudgetLedger(database_url()).snapshot()
            report["budget_before"] = budget_before
            owner = Identity(
                tenant_id="synthetic-p2-gate-" + uuid4().hex, user_id="safety-manager-demo"
            )
            folder = args.output.with_suffix(".facts")
            folder.mkdir(exist_ok=False)
            for name, key in (
                ("access.json", "access"),
                ("qualifications.json", "qualifications"),
                ("areas.json", "areas"),
            ):
                doc = copy.deepcopy(inputs[key])
                doc["version"] += "-p2-regression"
                for row in doc["records"]:
                    if row["tenant_id"] == "synthetic-demo":
                        row["tenant_id"] = owner.tenant_id
                (folder / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")

            def clock():
                return datetime.fromisoformat(suite["as_of"])

            embeddings = await LocalEmbeddings.create()
            check_embedding(embeddings.manifest, inputs["embedding"])
            knowledge = KnowledgeStore(database_url(), embeddings, clock=clock)
            await knowledge.initialize()
            for doc in inputs["corpus"]["documents"]:
                await knowledge.ingest(owner, doc)
            for doc_id in inputs["corpus"]["withdraw"]:
                await knowledge.withdraw(owner, doc_id)
            first_run = None
            for case in suite["cases"]:
                result = {"case_id": case["id"], "passed": False}
                try:
                    ident = case["id"]
                    if ident == "p2-10-platform":
                        result.update(await platform_check(first_run))
                    elif ident == "p2-11-budget-archive":
                        current = await BudgetLedger(database_url()).snapshot()
                        historical = inputs["budget_archive"]["attempts"]
                        result.update(check_budget(budget_before, current, historical))
                        report["budget_after"] = current
                        report["model_requests_this_run"] = result["new_reservations"]
                    elif ident == "p2-08-withdrawal":
                        template = next(
                            d for d in inputs["corpus"]["documents"] if d["doc_id"] == "watcher"
                        )
                        result["passed"] = await withdrawal_probe(knowledge, owner, template)
                    else:
                        service = WorkflowService(OfflineAnalyzer())
                        before = await service.start(owner, DEMO_FIELDS)
                        model = GateModel(ident)
                        refs = {
                            "worker_id": case.get("worker_id", "worker-001"),
                            "area_id": case.get("area_id", "area-001"),
                            "qualification_type": "welding",
                        }
                        trace = JsonlTrace(
                            args.output.with_suffix(".trace.jsonl"),
                            exporter=UnavailableExporter()
                            if ident == "p2-09-export-error"
                            else None,
                        )
                        store = (
                            UnavailableKnowledgeStore(clock)
                            if ident == "p2-07-knowledge-error"
                            else knowledge
                        )
                        actor = (
                            Identity(tenant_id="other", user_id=owner.user_id)
                            if ident == "p2-04-owner-denied"
                            else owner
                        )
                        try:
                            evidence = await check_facts_agent(
                                service,
                                actor,
                                before["task_id"],
                                refs,
                                FactTools(folder, clock=clock),
                                model,
                                trace,
                                knowledge_store=store,
                                knowledge_question=case.get("question", "监护人员如何安排？"),
                            )
                        except AccessDenied:
                            result["passed"] = (
                                ident == "p2-04-owner-denied"
                                and model.calls == 0
                                and await service.get(owner, before["task_id"]) == before
                            )
                        else:
                            after = await service.get(owner, before["task_id"])
                            result["evidence"] = evidence
                            result["material_unchanged"] = before == after
                            result["passed"] = check_result(evidence, case, before, after)
                            if ident == "p2-01-current":
                                first_run = evidence["run_id"]
                except Exception as exc:
                    result["error_category"] = type(exc).__name__
                report["results"].append(result)
                save()
            report["passed"] = sum(r["passed"] for r in report["results"])
            report["failed"] = len(suite["cases"]) - report["passed"]
            report["engineering_status"] = "passed" if report["failed"] == 0 else "failed"
        except Exception as exc:
            report["setup_error_category"] = type(exc).__name__
        finally:
            save()
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in (
                    "engineering_status",
                    "passed",
                    "failed",
                    "setup_error_category",
                    "model_requests_this_run",
                )
            }
        )
    )
    return 0 if report["engineering_status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop))
    except FileExistsError:
        parser.exit(2, "证据路径已存在，请使用新路径。\n")
