"""真实本地中文向量/pgvector开发对照；命中、摘录支持与未知分别报告。"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from anlan.contracts import Identity
from anlan.embeddings import LocalEmbeddings
from anlan.knowledge import KnowledgeStore
from anlan.postgres import database_url


def score(result, supporting_docs):
    gold = set(supporting_docs)
    citations = result["citations"]
    retrieved = [c["doc_id"] for c in citations]
    mapping = {c["chunk_id"]: c for c in citations}
    ranks = [index for index, doc_id in enumerate(retrieved, 1) if doc_id in gold]
    answers = result["answer"]
    supported = sum(mapping.get(a["chunk_id"], {}).get("doc_id") in gold for a in answers)
    return {
        "recall_at_k": len(gold & set(retrieved)) / len(gold) if gold else None,
        "reciprocal_rank": 1 / min(ranks) if ranks else (0 if gold else None),
        "answer_support_precision": supported / len(answers) if answers else None,
        "quote_fidelity": all(mapping.get(a["chunk_id"], {}).get("quote") == a["claim"]
                              for a in answers) if answers else None,
        "unknown_correct": (result["outcome"] == "unknown") == (not gold),
    }


async def evaluate(args):
    corpus_raw = Path("examples/synthetic/knowledge-v1/documents.json").read_bytes()
    dataset_raw = (Path(__file__).parent / "knowledge-v1/cases.json").read_bytes()
    corpus, dataset = json.loads(corpus_raw), json.loads(dataset_raw)
    report = {"created_at": datetime.now(UTC).isoformat(), "status": "running",
              "data_origin": "SYNTHETIC", "dataset_version": dataset["version"],
              "exposure": dataset["exposure"],
              "dataset_sha256": hashlib.sha256(dataset_raw).hexdigest(),
              "corpus_sha256": hashlib.sha256(corpus_raw).hexdigest(),
              "clock_mode": "simulated", "as_of": dataset["as_of"], "requests_this_run": 0,
              "encoding": "local_neural", "retrieval": "real_postgres_pgvector",
              "answer_mode": "top1-extractive-v2", "results": [], "ingested": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        save()
        try:
            embeddings = await LocalEmbeddings.create()
            report["embedding_manifest"] = embeddings.manifest
            identity = Identity(tenant_id="synthetic-knowledge-eval-" + uuid4().hex,
                                user_id="safety-manager-demo")
            report["tenant_id"] = identity.tenant_id
            store = KnowledgeStore(database_url(), embeddings,
                                   clock=lambda: datetime.fromisoformat(dataset["as_of"]))
            await store.initialize()
            for document in corpus["documents"]:
                report["ingested"].append(await store.ingest(identity, document))
                save()
            for doc_id in corpus["withdraw"]:
                await store.withdraw(identity, doc_id)
            for case in dataset["cases"]:
                for strategy in ("vector", "hybrid"):
                    started = perf_counter()
                    result = await store.search(identity, {
                        "question": case["question"], "top_k": dataset["top_k"],
                        "strategy": strategy, "minimum_score": dataset["minimum_score"],
                    })
                    report["results"].append({
                        "case_id": case["case_id"], "question": case["question"],
                        "strategy": strategy,
                        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                        "result": result, "scores": score(result, case["supporting_doc_ids"]),
                    })
                    save()
            summaries = {}
            for strategy in ("vector", "hybrid"):
                rows = [row for row in report["results"] if row["strategy"] == strategy]
                metrics = {}
                for metric in ("recall_at_k", "reciprocal_rank", "answer_support_precision"):
                    known = [r["scores"][metric] for r in rows if r["scores"][metric] is not None]
                    metrics[metric] = sum(known) / len(known) if known else None
                    metrics[metric + "_denominator"] = len(known)
                summaries[strategy] = {
                    **metrics, "cases": len(rows),
                    "unknown_correct": sum(r["scores"]["unknown_correct"] for r in rows),
                    "quote_fidelity": sum(r["scores"]["quote_fidelity"] is True for r in rows),
                    "quote_fidelity_denominator": sum(r["scores"]["quote_fidelity"] is not None
                                                       for r in rows),
                    "mean_elapsed_ms": sum(r["elapsed_ms"] for r in rows) / len(rows),
                }
            report["summary"] = summaries
            report["status"] = "completed"
        except Exception as exc:
            report["status"] = "failed"
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({"status": report["status"], "summary": report.get("summary"),
                      "output": str(args.output)}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(evaluate(args), loop_factory=asyncio.SelectorEventLoop))
    except FileExistsError:
        parser.exit(2, "结果已存在；使用新路径，不覆盖旧证据。\n")
