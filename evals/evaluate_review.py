"""Same-task context ablation, real read-only tools/PG, explicitly scripted or live synthesis."""

import argparse
import asyncio
import hashlib
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from evaluate_rag import derive_fact_fixture

from anlan.analysis import OfflineAnalyzer
from anlan.budget import BudgetLedger
from anlan.contracts import Identity
from anlan.embeddings import LocalEmbeddings
from anlan.knowledge import KnowledgeStore
from anlan.memory import MemoryStore
from anlan.model import ModelConfig
from anlan.postgres import database_url, postgres_service
from anlan.review import (
    WORK_PACKAGE,
    DeepSeekReviewModel,
    ScriptedReviewModel,
    collect_review,
    synthesize,
)
from anlan.tools.queries import FactTools
from anlan.trace import JsonlTrace

ROOT = Path(__file__).resolve().parents[1]
ARMS = [("no_memory", False, True), ("with_memory", True, True), ("no_knowledge", True, False)]


def score(result, case, use_memory, use_knowledge):
    candidate = result["candidate"]
    data = json.loads(result["context"]["messages"][1]["content"]) if result["context"] else {}
    expected = {
        "detail_level": "detailed" if use_memory else "brief",
        "presentation_order": "sources_first" if use_memory else "unknowns_first",
    }
    observed = result["observations"]
    expected_facts = [
        {"status": "active", "qualification_type": "welding"},
        {"status": "restricted"},
    ]
    facts_match = len(observed) >= 2 and all(
        o["reason"] == case["fact_reason"]
        and o["outcome"] == ("unknown" if case["fact_reason"] else "ok")
        and o["facts"] == (None if case["fact_reason"] else expected_facts[i])
        for i, o in enumerate(observed[:2])
    )
    citations = (
        [c for claim in candidate["claims"] for c in claim["knowledge_citations"]]
        if candidate
        else []
    )
    chunks = {c["chunk_id"]: c for c in data.get("knowledge", [])}
    return {
        "completed": result["stop_reason"] == "completed",
        "facts_match": facts_match,
        "presentation_fields_match": bool(candidate and candidate["presentation"] == expected),
        "unknowns_complete": bool(
            candidate
            and set(candidate["unknown_observation_ids"])
            == {f"o{i}" for i, o in enumerate(observed, 1) if o["outcome"] != "ok"}
        ),
        "selected_knowledge_source_matches": bool(candidate)
        and (bool(citations) == bool(case["supporting_doc_ids"] and use_knowledge))
        and all(
            c["chunk_id"] in chunks
            and chunks[c["chunk_id"]]["doc_id"] in case["supporting_doc_ids"]
            for c in citations
        ),
        "claim_characters": sum(len(c["text"]) for c in candidate["claims"]) if candidate else 0,
        "semantic_support": "manual_review_required_not_inferred_from_citation_presence",
    }


def experiment_attempts(before, after, run_ids):
    old_ids = {a["attempt_id"] for a in before.get("attempts", [])}
    added = [a for a in after["attempts"] if a["attempt_id"] not in old_ids]
    return (
        [a for a in added if a["run_id"] in run_ids],
        [a for a in added if a["run_id"] not in run_ids],
    )


async def evaluate(args):
    raw = (ROOT / "evals/review-v1/cases.json").read_bytes()
    dataset = json.loads(raw)
    corpus_raw = (ROOT / "examples/synthetic/knowledge-v1/documents.json").read_bytes()
    corpus = json.loads(corpus_raw)
    now = datetime.fromisoformat(dataset["as_of"])
    identity = Identity(tenant_id="synthetic-review-" + uuid4().hex, user_id="safety-manager-demo")
    report = {
        "data_origin": "SYNTHETIC",
        "exposure": "developer_seen",
        "mode": args.mode,
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "corpus_sha256": hashlib.sha256(corpus_raw).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "as_of": dataset["as_of"],
        "tenant_id": identity.tenant_id,
        "work_package": WORK_PACKAGE,
        "automatic_retries": 0,
        "results": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ledger = BudgetLedger(database_url())
    report["experiment_run_ids"] = []
    with args.output.open("x", encoding="utf-8") as output:

        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        save()
        try:
            report["budget_before"] = await ledger.snapshot()
            before = report["budget_before"]
            if args.mode == "deepseek" and (
                before["total_reserved"] + 9 > before["total_limit"]
                or before["packages"].get(WORK_PACKAGE, 0) + 9 > before["package_limit"]
            ):
                raise ValueError("Insufficient shared budget for the prespecified 9 attempts")
            config = ModelConfig.from_env() if args.mode == "deepseek" else None
            facts_dir = args.output.with_suffix(".facts")
            report["derived_facts"] = derive_fact_fixture(facts_dir, identity.tenant_id)
            embeddings = await LocalEmbeddings.create()
            report["embedding_manifest"] = embeddings.manifest
            knowledge = KnowledgeStore(database_url(), embeddings, clock=lambda: now)
            await knowledge.initialize()
            for doc in corpus["documents"]:
                await knowledge.ingest(identity, doc)
            for doc_id in corpus["withdraw"]:
                await knowledge.withdraw(identity, doc_id)
            memory = MemoryStore(database_url(), clock=lambda: now)
            await memory.initialize()
            for key, value in (
                ("detail_level", "detailed"),
                ("presentation_order", "sources_first"),
            ):
                source = await memory.feedback(
                    identity,
                    {
                        "data_origin": "SYNTHETIC",
                        "source_ref": "review-feedback-" + key,
                        "version": 1,
                        "key": key,
                        "value": value,
                        "observed_at": "2026-09-19T00:00:00Z",
                        "expires_at": "2026-09-30T00:00:00Z",
                    },
                )
                m = await memory.propose(identity, source["source_ref"], 1)
                await memory.change(identity, m["memory_id"], 1, "confirm")
            async with AsyncExitStack() as stack:
                service = await stack.enter_async_context(
                    postgres_service(database_url(), OfflineAnalyzer())
                )
                client = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=False))
                for case in dataset["cases"]:
                    state = await service.start(identity, case["fields"])
                    bundle = await collect_review(
                        service,
                        identity,
                        state["task_id"],
                        {
                            "worker_id": case["worker_id"],
                            "area_id": case["area_id"],
                            "qualification_type": "welding",
                        },
                        case["question"],
                        FactTools(facts_dir, clock=lambda: now),
                        knowledge,
                        memory,
                        JsonlTrace(args.output.with_suffix(".trace.jsonl")),
                    )
                    # Each distinct task gets at most 3 requests, all sharing the persistent ledger.
                    model = (
                        DeepSeekReviewModel(config, client, ledger)
                        if config
                        else ScriptedReviewModel()
                    )
                    for arm, use_memory, use_knowledge in ARMS:
                        run_id = str(uuid4())
                        report["experiment_run_ids"].append(run_id)
                        report["active_case"] = {
                            "case_id": case["case_id"],
                            "arm": arm,
                            "run_id": run_id,
                        }
                        save()
                        result = await synthesize(
                            bundle,
                            model,
                            use_memory=use_memory,
                            use_knowledge=use_knowledge,
                            trace=JsonlTrace(args.output.with_suffix(".trace.jsonl")),
                            run_id=run_id,
                        )
                        report["results"].append(
                            {
                                "case_id": case["case_id"],
                                "arm": arm,
                                "bundle": bundle,
                                "evidence": result,
                                "material_unchanged": await service.get(identity, state["task_id"])
                                == state,
                                "scores": score(result, case, use_memory, use_knowledge),
                            }
                        )
                        report["budget_after"] = await ledger.snapshot()
                        save()
            report["status"] = "completed"
            report.pop("active_case", None)
        except Exception as exc:
            report.update(status="failed", error_category=type(exc).__name__)
        finally:
            try:
                report["budget_after"] = await ledger.snapshot()
                attempts, other = experiment_attempts(
                    report.get("budget_before", {}),
                    report["budget_after"],
                    set(report["experiment_run_ids"]),
                )
                report["new_attempts"] = attempts
                report["other_new_attempts"] = other
                report["requests_this_run"] = len(attempts)
                report["known_tokens"] = sum(
                    (a["usage"] or {}).get("total_tokens") or 0 for a in attempts
                )
                report["usage_complete"] = all(
                    a["usage"]
                    and all(
                        type(a["usage"].get(k)) is int
                        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    )
                    for a in attempts
                )
            except Exception:
                report["budget_warning"] = "snapshot_unavailable"
            save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "rows": len(report["results"]),
                "requests": report.get("requests_this_run"),
                "error": report.get("error_category"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(args), loop_factory=asyncio.SelectorEventLoop))
