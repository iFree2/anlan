"""Same frozen P3 tasks: one synthesis vs two bounded model roles, at most nine calls."""

import argparse
import asyncio
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from evaluate_review import experiment_attempts, score

from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.llm.config import ModelConfig
from anlan.llm.evidence_review import WORK_PACKAGE, DeepSeekEvidenceModel, ScriptedEvidenceModel
from anlan.llm.review_model import DeepSeekReviewModel, ScriptedReviewModel
from anlan.memory.store import MemoryStore
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.multi_review import multi_review
from anlan.workflows.parallel import canonical_observations, collect_parallel
from anlan.workflows.review import synthesize

ROOT = Path(__file__).resolve().parents[1]


async def evaluate(args):
    raw = (ROOT / "evals/review-v1/cases.json").read_bytes()
    dataset = json.loads(raw)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    if (
        source["status"] != "completed"
        or source["dataset_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError("Use a completed matching real-tool comparison as task source")
    now = datetime.fromisoformat(dataset["as_of"])
    report = {
        "data_origin": "SYNTHETIC",
        "exposure": "developer_seen",
        "mode": args.mode,
        "work_package": WORK_PACKAGE,
        "status": "running",
        "results": [],
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
        "automatic_retries": 0,
        "experiment_run_ids": [],
        "planned_request_ceiling": 9,
        "normalization": "elapsed_ms removed before both arms, raw observations retained",
    }
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
            before = report["budget_before"] = await ledger.snapshot()
            if args.mode == "deepseek" and (
                before["total_reserved"] + 9 > before["total_limit"]
                or before["packages"].get(WORK_PACKAGE, 0) + 9 > before["package_limit"]
            ):
                raise ValueError("Insufficient budget for predeclared experiment")
            config = ModelConfig.from_env() if args.mode == "deepseek" else None
            embeddings = await LocalEmbeddings.create()
            report["embedding_manifest"] = embeddings.manifest
            knowledge = KnowledgeStore(database_url(), embeddings, clock=lambda: now)
            memory = MemoryStore(database_url(), clock=lambda: now)
            trace = JsonlTrace(args.output.with_suffix(".trace.jsonl"))
            async with postgres_service(database_url(), OfflineAnalyzer()) as service:
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    for case in dataset["cases"]:
                        original = next(
                            r["bundle"]
                            for r in source["results"]
                            if r["case_id"] == case["case_id"] and r["arm"] == "parallel"
                        )
                        identity = Identity.model_validate(original["identity"])
                        refs = original["collection"]["children"][0]["input"]["parameters"]
                        bundle = await collect_parallel(
                            service,
                            identity,
                            original["snapshot"]["task_id"],
                            refs,
                            case["question"],
                            FactTools(args.source.with_suffix(".facts"), clock=lambda: now),
                            knowledge,
                            memory,
                            trace=trace,
                        )
                        if bundle["snapshot"] != original["snapshot"]:
                            raise ValueError("Source material revision changed")
                        raw_bundle = copy.deepcopy(bundle)
                        bundle["observations"] = canonical_observations(bundle["observations"])
                        for arm in ("single", "multi"):
                            parent = str(uuid4())
                            ids = (
                                [parent]
                                if arm == "single"
                                else [parent + ":risk", parent + ":evidence"]
                            )
                            report["experiment_run_ids"].extend(ids)
                            report["active_case"] = {
                                "case_id": case["case_id"],
                                "arm": arm,
                                "parent_run_id": parent,
                                "run_ids": ids,
                            }
                            save()  # Persist ownership before any HTTP attempt.
                            risk = (
                                DeepSeekReviewModel(
                                    config, client, ledger, work_package=WORK_PACKAGE
                                )
                                if config
                                else ScriptedReviewModel()
                            )
                            if arm == "single":
                                result = await synthesize(
                                    bundle,
                                    risk,
                                    trace=trace,
                                    run_id=parent,
                                    work_package=WORK_PACKAGE,
                                )
                                comparable = result
                            else:
                                audit = (
                                    DeepSeekEvidenceModel(config, client, ledger)
                                    if config
                                    else ScriptedEvidenceModel()
                                )
                                result = await multi_review(
                                    bundle, risk, audit, trace=trace, run_id=parent
                                )
                                comparable = result["risk"]
                            report["results"].append(
                                {
                                    "case_id": case["case_id"],
                                    "arm": arm,
                                    "bundle": raw_bundle,
                                    "evidence": result,
                                    "scores": score(comparable, case, True, True)
                                    if comparable
                                    else None,
                                    "material_unchanged": await service.get(
                                        identity, bundle["snapshot"]["task_id"]
                                    )
                                    == bundle["snapshot"],
                                }
                            )
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
                report.update(
                    new_attempts=attempts, other_new_attempts=other, requests_this_run=len(attempts)
                )
                report["usage"] = {
                    k: sum((a["usage"] or {}).get(k) or 0 for a in attempts)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
                report["usage_complete"] = all(
                    a["usage"] and all(type(a["usage"].get(k)) is int for k in report["usage"])
                    for a in attempts
                )
                if (
                    len(attempts) > 9
                    or any(a["work_package"] != WORK_PACKAGE for a in attempts)
                    or (args.mode == "scripted" and attempts)
                ):
                    report.update(status="failed", error_category="request_accounting_mismatch")
            except Exception:
                report.update(status="failed", budget_warning="snapshot_unavailable")
            save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "rows": len(report["results"]),
                "requests": report.get("requests_this_run"),
                "usage": report.get("usage"),
            }
        )
    )
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    raise SystemExit(
        asyncio.run(evaluate(parser.parse_args()), loop_factory=asyncio.SelectorEventLoop)
    )
