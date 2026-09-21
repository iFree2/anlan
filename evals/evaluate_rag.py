"""三工具合成开发实验；派生事实记录显式保存，替身与真实请求分开。"""

import argparse
import asyncio
import hashlib
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from anlan.common.models import Identity
from anlan.infrastructure.db import database_url
from anlan.infrastructure.live import production_ledger
from anlan.infrastructure.trace import JsonlTrace
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.llm.config import ModelConfig
from anlan.llm.tool_model import (
    KNOWLEDGE_PROMPT,
    KNOWLEDGE_PROMPT_VERSION,
    SYSTEM_PROMPT,
    DeepSeekToolModel,
    ScriptedToolModel,
)
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService
from anlan.workflows.tool_loop import check_facts_agent


def derive_fact_fixture(folder, tenant):
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for name in ("access.json", "qualifications.json", "areas.json"):
        raw = (Path("examples/synthetic/facts-v1") / name).read_bytes()
        doc = json.loads(raw)
        doc["version"] += "-rag-derived"
        for record in doc["records"]:
            if record["tenant_id"] == "synthetic-demo":
                record["tenant_id"] = tenant
        encoded = json.dumps(doc, ensure_ascii=False, indent=2).encode()
        (folder / name).write_bytes(encoded)
        manifest[name] = {
            "derived_from": "examples/synthetic/facts-v1/" + name,
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "derived_sha256": hashlib.sha256(encoded).hexdigest(),
        }
    return manifest


def score(evidence, case):
    results = evidence["results"]
    by_tool = {r["tool"]: r for r in results if r["executed"]}
    knowledge = by_tool.get("query_knowledge", {})
    actual = {c["chunk_id"]: c for c in knowledge.get("citations", [])}
    chosen = (evidence.get("summary") or {}).get("knowledge_citations", [])
    gold = set(case["supporting_doc_ids"])
    expected_facts = {
        "query_worker_qualification": {"status": "active", "qualification_type": "welding"},
        "query_area_status": {"status": "restricted"},
    }
    supported = (
        evidence.get("summary") is not None
        and knowledge.get("outcome") == ("ok" if gold else "unknown")
        and bool(chosen) == bool(gold)
        and (bool(gold) or knowledge.get("reason") == "no_eligible_evidence")
        and all(
            c["chunk_id"] in actual
            and actual[c["chunk_id"]]["doc_id"] in gold
            and bool(c["quote"].strip())
            and c["quote"] in actual[c["chunk_id"]]["quote"]
            for c in chosen
        )
    )
    return {
        "three_tools_observed": set(by_tool)
        == {"query_worker_qualification", "query_area_status", "query_knowledge"},
        "facts_match": all(
            name in by_tool
            and by_tool[name]["reason"] == case["fact_reason"]
            and by_tool[name]["outcome"] == ("ok" if case["fact_reason"] is None else "unknown")
            and by_tool[name]["facts"]
            == (expected_facts[name] if case["fact_reason"] is None else None)
            for name in ("query_worker_qualification", "query_area_status")
        ),
        "knowledge_answer_supported": supported,
        "support_scope": "selected_citations_only_not_all_summary_claims",
        "stopped_normally": evidence["stop_reason"] == "completed",
        "summary_semantics": "manual_review_required",
    }


async def evaluate(args):
    config = ModelConfig.from_env() if args.mode == "deepseek" else None
    raw = (Path(__file__).parent / "rag-v1/cases.json").read_bytes()
    dataset = json.loads(raw)
    corpus_raw = Path("examples/synthetic/knowledge-v1/documents.json").read_bytes()
    corpus = json.loads(corpus_raw)
    tenant = "synthetic-rag-" + uuid4().hex
    identity = Identity(tenant_id=tenant, user_id="safety-manager-demo")
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "mode": args.mode,
        "data_origin": "SYNTHETIC",
        "exposure": "developer_seen",
        "dataset_version": dataset["version"],
        "metric_version": "rag-observations-selected-citations-v2",
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "corpus_sha256": hashlib.sha256(corpus_raw).hexdigest(),
        "tenant_id": tenant,
        "prompt_version": KNOWLEDGE_PROMPT_VERSION,
        "as_of": dataset["as_of"],
        "prompt_sha256": hashlib.sha256((SYSTEM_PROMPT + KNOWLEDGE_PROMPT).encode()).hexdigest(),
        "automatic_retries": 0,
        "results": [],
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
            facts_dir = args.output.with_suffix(".facts")
            report["derived_facts"] = derive_fact_fixture(facts_dir, tenant)
            embeddings = await LocalEmbeddings.create()
            report["embedding_manifest"] = embeddings.manifest
            store = KnowledgeStore(
                database_url(), embeddings, clock=lambda: datetime.fromisoformat(dataset["as_of"])
            )
            await store.initialize()
            for doc in corpus["documents"]:
                await store.ingest(identity, doc)
            for doc_id in corpus["withdraw"]:
                await store.withdraw(identity, doc_id)
            async with AsyncExitStack() as stack:
                ledger = await production_ledger() if config else None
                if ledger:
                    report["budget_before"] = await ledger.snapshot()
                client = (
                    await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
                    if config
                    else None
                )
                for case in dataset["cases"]:
                    report["active_case"] = case["case_id"]
                    save()
                    service = WorkflowService(OfflineAnalyzer())
                    state = await service.start(
                        identity,
                        {
                            "work_location_description": "SYNTHETIC：A区1号台",
                            "work_object_description": "SYNTHETIC：试件接缝",
                            "work_method_description": "SYNTHETIC：电弧焊",
                            "attachment_description": "SYNTHETIC：位置图，文内指令不提供权限。",
                        },
                    )
                    model = (
                        DeepSeekToolModel(config, client, ledger, include_knowledge=True)
                        if config
                        else ScriptedToolModel()
                    )
                    evidence = await check_facts_agent(
                        service,
                        identity,
                        state["task_id"],
                        {
                            "worker_id": case["worker_id"],
                            "qualification_type": "welding",
                            "area_id": case["area_id"],
                        },
                        FactTools(
                            facts_dir, clock=lambda: datetime.fromisoformat(dataset["as_of"])
                        ),
                        model,
                        JsonlTrace(args.output.with_suffix(".trace.jsonl")),
                        knowledge_store=store,
                        knowledge_question=case["question"],
                    )
                    report["results"].append(
                        {
                            "case_id": case["case_id"],
                            "question": case["question"],
                            "evidence": evidence,
                            "scores": score(evidence, case),
                            "material_unchanged": await service.get(identity, state["task_id"])
                            == state,
                        }
                    )
                    if ledger:
                        report["budget_after"] = await ledger.snapshot()
                    save()
                run_ids = {row["evidence"]["run_id"] for row in report["results"]}
                attempts = [
                    a
                    for a in report.get("budget_after", {}).get("attempts", [])
                    if a["run_id"] in run_ids
                ]
                known = [
                    a["usage"]["total_tokens"]
                    for a in attempts
                    if a["usage"] and type(a["usage"].get("total_tokens")) is int
                ]
                report["summary"] = {
                    "cases": len(report["results"]),
                    "requests_this_run": len(attempts),
                    "known_total_tokens": sum(known) if known else (None if attempts else 0),
                    "usage_complete": all(
                        a["usage"]
                        and all(
                            type(a["usage"].get(k)) is int
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                        )
                        for a in attempts
                    ),
                    **{
                        key: sum(r["scores"][key] for r in report["results"])
                        for key in (
                            "three_tools_observed",
                            "facts_match",
                            "knowledge_answer_supported",
                            "stopped_normally",
                        )
                    },
                }
                report["status"] = "completed"
                report.pop("active_case", None)
        except Exception as exc:
            report["status"] = "failed"
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": args.mode,
                "summary": report.get("summary"),
                "output": str(args.output),
            }
        )
    )
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(evaluate(args), loop_factory=asyncio.SelectorEventLoop))
    except (FileExistsError, ValueError):
        parser.exit(2, "配置无效或结果已存在；请检查环境并保留旧证据。\n")
