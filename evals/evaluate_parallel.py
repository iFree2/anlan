"""P4-WP01 same-task three-arm collection comparison with real PG/BGE and no model requests."""

import argparse
import asyncio
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from evaluate_rag import derive_fact_fixture
from evaluate_review import score

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.llm.review_model import ScriptedReviewModel
from anlan.memory.store import MemoryStore
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.parallel import WORK_PACKAGE, canonical_observations, collect_parallel
from anlan.workflows.review import collect_review, synthesize

ROOT = Path(__file__).resolve().parents[1]
SCORES = ("completed", "facts_match", "presentation_fields_match", "unknowns_complete",
          "selected_knowledge_source_matches")


def equivalent(left, right):
    return (all(left[key] == right[key] for key in
                ("snapshot", "identity", "as_of", "question", "memories"))
            and canonical_observations(left["observations"])
            == canonical_observations(right["observations"]))


async def evaluate(args):
    raw = (ROOT / "evals/review-v1/cases.json").read_bytes()
    dataset = json.loads(raw)
    corpus_raw = (ROOT / "examples/synthetic/knowledge-v1/documents.json").read_bytes()
    corpus = json.loads(corpus_raw)
    now = datetime.fromisoformat(dataset["as_of"])
    identity = Identity(tenant_id="synthetic-parallel-" + uuid4().hex,
                        user_id="safety-manager-demo")
    report = {"data_origin": "SYNTHETIC", "exposure": "developer_seen",
              "work_package": WORK_PACKAGE, "mode": "deterministic_branches_scripted_synthesis",
              "status": "running", "created_at": datetime.now(UTC).isoformat(),
              "dataset_sha256": hashlib.sha256(raw).hexdigest(),
              "corpus_sha256": hashlib.sha256(corpus_raw).hexdigest(),
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "as_of": dataset["as_of"], "tenant_id": identity.tenant_id, "results": [],
              "requests_this_run": 0, "tokens": None,
              "normalization": "Only elapsed_ms removed equally before synthesis; raw retained",
              "quality_claim": "Engineering equivalence only; no model or generalization gain"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ledger = BudgetLedger(database_url())
    with args.output.open("x", encoding="utf-8") as output:
        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()
        save()
        try:
            report["budget_before"] = await ledger.snapshot()
            facts_dir = args.output.with_suffix(".facts")
            report["derived_facts"] = derive_fact_fixture(facts_dir, identity.tenant_id)
            embeddings = await LocalEmbeddings.create()
            report["embedding_manifest"] = embeddings.manifest
            knowledge = KnowledgeStore(database_url(), embeddings, clock=lambda: now)
            await knowledge.initialize()
            for doc in corpus["documents"]:
                await knowledge.ingest(identity, doc)
            for doc in corpus["withdraw"]:
                await knowledge.withdraw(identity, doc)
            memory = MemoryStore(database_url(), clock=lambda: now)
            await memory.initialize()
            for key, value in (("detail_level", "detailed"),
                               ("presentation_order", "sources_first")):
                source = await memory.feedback(identity, {"data_origin": "SYNTHETIC",
                    "source_ref": "parallel-feedback-" + key, "version": 1, "key": key,
                    "value": value, "observed_at": "2026-09-19T00:00:00Z",
                    "expires_at": "2026-09-30T00:00:00Z"})
                m = await memory.propose(identity, source["source_ref"], 1)
                await memory.change(identity, m["memory_id"], 1, "confirm")
            trace = JsonlTrace(args.output.with_suffix(".trace.jsonl"))
            async with postgres_service(database_url(), OfflineAnalyzer()) as service:
                for case in dataset["cases"]:
                    state = await service.start(identity, case["fields"])
                    refs = {"worker_id": case["worker_id"], "area_id": case["area_id"],
                            "qualification_type": "welding"}
                    rows = []
                    for arm in ("baseline", "serial", "parallel"):
                        collector = collect_review if arm == "baseline" else collect_parallel
                        options = {} if arm == "baseline" else {"parallel": arm == "parallel"}
                        bundle = await collector(service, identity, state["task_id"], refs,
                            case["question"], FactTools(facts_dir, clock=lambda: now), knowledge,
                            memory, trace=trace, **options)
                        normalized = copy.deepcopy(bundle)
                        normalized["observations"] = canonical_observations(bundle["observations"])
                        result = await synthesize(normalized, ScriptedReviewModel(), trace=trace)
                        result["work_package"] = WORK_PACKAGE
                        row = {"case_id": case["case_id"], "arm": arm, "bundle": bundle,
                               "evidence": result, "scores": score(result, case, True, True),
                               "material_unchanged": await service.get(identity, state["task_id"])
                               == state}
                        rows.append(row)
                        report["results"].append(row)
                        save()
                    for row in rows:
                        row["same_evidence"] = equivalent(rows[0]["bundle"], row["bundle"])
                        row["same_context"] = (rows[0]["evidence"]["context"]["sha256"]
                                               == row["evidence"]["context"]["sha256"])
                        row["same_candidate"] = (rows[0]["evidence"]["candidate"]
                                                 == row["evidence"]["candidate"])
                    outsider = identity.model_copy(update={"user_id": "outsider"})
                    try:
                        await collect_parallel(service, outsider, state["task_id"], refs,
                            case["question"], None, None, None)
                    except AccessDenied:
                        rows[-1]["pg_unauthorized_rejected"] = True
                    else:
                        raise ValueError("Authorization gate bypassed")
            report["budget_after"] = await ledger.snapshot()
            if report["budget_before"] != report["budget_after"]:
                raise ValueError("Model ledger changed during a zero-request experiment")
            if len(report["results"]) != 9 or not all(
                r["material_unchanged"] and r["same_evidence"] and r["same_context"]
                and r["same_candidate"] and all(r["scores"][k] is True for k in SCORES)
                and r["evidence"]["requests_this_run"] == 0 for r in report["results"]
            ):
                raise ValueError("Comparison failed; original rows retained")
            report["status"] = "completed"
        except Exception as exc:
            report.update(status="failed", error_category=type(exc).__name__)
        finally:
            save()
    print(json.dumps({"status": report["status"], "rows": len(report["results"]),
                      "requests": report["requests_this_run"]}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(asyncio.run(evaluate(parser.parse_args()),
                                loop_factory=asyncio.SelectorEventLoop))
