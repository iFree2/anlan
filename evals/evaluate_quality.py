"""Frozen finite Judge calibration and single/dual review; at most eight P6 requests."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.llm.config import ModelConfig
from anlan.llm.evidence_review import DeepSeekEvidenceModel, ScriptedEvidenceModel
from anlan.llm.review_model import DeepSeekReviewModel, ScriptedReviewModel
from anlan.workflows.judge_calibration import (
    WORK_PACKAGE,
    ablate_audit,
    calibration_context,
    score_calibration,
)
from anlan.workflows.multi_review import multi_review
from anlan.workflows.review import synthesize

ROOT = Path(__file__).resolve().parents[1]
DATASET_SHA = "003d77eb54083ba9f9980fae9e09c1fd5473b2e0668840cd55c58bc6f7eb49d4"


async def execute(data, report, save, ledger, client, config):
    models = []
    before = report["budget_before"] = await ledger.snapshot()
    save()
    if config and (before["total_reserved"] + 8 > before["total_limit"]
                   or before["packages"].get(WORK_PACKAGE, 0) + 8 > before["package_limit"]):
        raise ValueError("Insufficient shared budget for the predeclared experiment")

    def risk_model():
        model = (DeepSeekReviewModel(config, client, ledger, work_package=WORK_PACKAGE)
                 if config else ScriptedReviewModel())
        models.append(model)
        return model

    def audit_model():
        model = (DeepSeekEvidenceModel(config, client, ledger, work_package=WORK_PACKAGE)
                 if config else ScriptedEvidenceModel())
        models.append(model)
        return model

    try:
        for case in data["cases"]:
            context = calibration_context(case, data["rubric"])
            model, run_id = audit_model(), str(uuid4())
            row = {"case_id": case["id"], "run_id": run_id, "context": context,
                   "review": None, "attempt_id": None, "usage": None}
            report["judge"].append(row)
            report["run_ids"].append(run_id)
            save()
            started = perf_counter()
            try:
                row.update(await model.generate(context, run_id))
                row["stop_reason"] = "completed"
            except Exception as exc:
                row["stop_reason"] = getattr(exc, "category", "model_error")
                row["usage"] = getattr(exc, "usage", None)
                row["attempt_id"] = model.gateway.last_attempt_id if config else None
            row["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
            row["scores"] = score_calibration(row["review"], context, case["gold"])
            save()

            single_run, parent = str(uuid4()), str(uuid4())
            pair = {"case_id": case["id"], "bundle": case["bundle"], "single": None,
                    "multi": None, "ablation": None}
            report["results"].append(pair)
            report["run_ids"].append(single_run)
            save()
            pair["single"] = await synthesize(case["bundle"], risk_model(),
                                              run_id=single_run, work_package=WORK_PACKAGE)
            report["run_ids"].extend([parent + ":risk", parent + ":evidence"])
            save()
            pair["multi"] = await multi_review(case["bundle"], risk_model(), audit_model(),
                                                run_id=parent, work_package=WORK_PACKAGE)
            pair["ablation"] = ablate_audit(pair["multi"])
            multi_risk = pair["multi"]["risk"]
            pair["same_risk_context"] = bool(
                multi_risk and multi_risk["context"] and pair["single"]["context"]
                and multi_risk["context"]["sha256"] == pair["single"]["context"]["sha256"]
            )
            save()
    finally:
        observed = {m.gateway.last_attempt_id for m in models if hasattr(m, "gateway")
                    and m.gateway.last_attempt_id is not None}
        report.update(observed_attempt_ids=sorted(observed),
                      requests_observed_lower_bound=len(observed),
                      requests_this_run=None if config else 0,
                      request_accounting_complete=False)
        save()
        try:
            after = report["budget_after"] = await ledger.snapshot()
        except Exception:
            report["budget_warning"] = "snapshot_unavailable"
            save()
            raise
        old = {a["attempt_id"] for a in before["attempts"]}
        owned = set(report["run_ids"])
        new = [a for a in after["attempts"] if a["attempt_id"] not in old]
        attempts = [a for a in new if a["run_id"] in owned]
        report["other_new_attempts"] = [a for a in new if a["run_id"] not in owned]
        report["new_attempts"] = attempts
        report["requests_this_run"] = len(attempts)
        report["request_accounting_complete"] = True
        report["usage"] = {k: sum((a.get("usage") or {}).get(k) or 0 for a in attempts)
                           for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        report["usage_complete"] = all(
            a.get("usage") and all(type(a["usage"].get(k)) is int for k in report["usage"])
            for a in attempts
        )
        package = lambda a: a.get("work_package", a.get("package"))  # noqa: E731
        if len(attempts) > 8 or any(package(a) != WORK_PACKAGE for a in attempts) or (
            config is None and attempts
        ):
            raise ValueError("Unexpected model request accounting")
        save()


async def evaluate(args):
    raw = (ROOT / "evals/judge-v1/cases.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATASET_SHA:
        raise ValueError("Frozen calibration dataset changed")
    data = json.loads(raw)
    sources = [Path(__file__).resolve(), *[ROOT / p for p in (
        "src/anlan/workflows/judge_calibration.py", "src/anlan/workflows/multi_review.py",
        "src/anlan/workflows/review.py", "src/anlan/llm/evidence_review.py",
        "src/anlan/llm/review_model.py", "src/anlan/llm/gateway.py")]]
    report = {"status": "failed", "mode": args.mode, "data_origin": "SYNTHETIC",
              "work_package": WORK_PACKAGE, "exposure": "developer_seen",
              "observation_origin": data["observation_origin"], "dataset_sha256": DATASET_SHA,
              "planned_request_ceiling": 8, "automatic_retries": 0, "run_ids": [],
              "judge": [], "results": [], "requests_this_run": 0,
              "sources": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sources}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        def save():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()

        save()
        try:
            config = (ModelConfig.from_env().model_copy(update={"max_requests": 1})
                      if args.mode == "deepseek" else None)
            async with httpx.AsyncClient(follow_redirects=False) as client:
                await execute(data, report, save, BudgetLedger(database_url()), client, config)
            report["status"] = "completed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({k: report.get(k) for k in
                      ("status", "mode", "requests_this_run", "usage", "error_category")}))
    return int(report["status"] != "completed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(asyncio.run(evaluate(parser.parse_args()),
                                 loop_factory=asyncio.SelectorEventLoop))
