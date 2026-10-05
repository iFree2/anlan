"""One synthetic confined-space transfer: existing PG/assets, no business-rule migration."""

import argparse
import asyncio
import copy
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.interfaces.runtime import postgres_service
from anlan.memory.contracts import MemoryConflict
from anlan.memory.store import MemoryStore
from anlan.tools.queries import FactTools
from anlan.workflows.material_analysis import OfflineAnalyzer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "examples/synthetic/confined-space-v1"


def require(value):
    if not value:
        raise ValueError("Reuse evidence contract failed")


def transfer(fixture, observations, preferences):
    require(fixture.get("data_origin") == "SYNTHETIC"
            and fixture.get("task_kind") == "confined_space_demo")
    return {"data_origin": "SYNTHETIC", "status": "requires_human_review",
            "observations": copy.deepcopy(observations),
            "unknown_observation_ids": [f"o{i}" for i, row in enumerate(observations, 1)
                                        if row["outcome"] != "ok"],
            "presentation": dict(preferences), "business_rules_reused": False,
            "unverified_domain_inputs": fixture.get("unverified_domain_inputs", []),
            "notice": "合成资料移交；不是受限空间判断或作业批准"}


async def evaluate(output, report, save):
    fixture = json.loads((DATA / "task.json").read_text(encoding="utf-8"))
    transfer(fixture, [], {})  # Domain boundary checked before any PG work.
    now = datetime.fromisoformat(fixture["as_of"])
    identity = Identity(**(fixture["identity"] | {"user_id": "reuse-" + uuid4().hex}))
    dsn = database_url()
    ledger = BudgetLedger(dsn)
    report["budget_before"] = await ledger.snapshot()
    report["identity"] = identity.model_dump()
    report["fixture_sha256"] = {p.relative_to(DATA).as_posix():
                                hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(DATA.rglob("*.json"))}
    report["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save()
    facts = output / "facts"
    facts.mkdir()
    for path in (DATA / "facts").glob("*.json"):
        raw = path.read_text(encoding="utf-8").replace(
            fixture["identity"]["user_id"], identity.user_id)
        (facts / path.name).write_text(raw, encoding="utf-8")
    async with postgres_service(dsn, OfflineAnalyzer()) as service:
        first = await service.start(identity, fixture["fields"])
        report["material_start"] = first
        save()
        require(first["status"] == "waiting_input")
        final = await service.resume(identity, first["task_id"], first["revision"],
                                     fixture["supplement"], request_id="supply-method")
        report["material_completed"] = final
        require(final["status"] == "awaiting_review")
    async with postgres_service(dsn, OfflineAnalyzer()) as service:
        require(await service.get(identity, first["task_id"]) == final)
        try:
            await service.get(Identity(tenant_id="other-synthetic", user_id=identity.user_id),
                              first["task_id"])
        except AccessDenied:
            report["material_cross_tenant_denied"] = True
        else:
            raise ValueError("Cross tenant material read accepted")
    save()
    tools = FactTools(facts, clock=lambda: now)
    refs = fixture["refs"]
    observations = [
        await tools.query_worker_qualification(identity, {k: refs[k] for k in (
            "worker_id", "qualification_type")}),
        await tools.query_area_status(identity, {"area_id": refs["area_id"]}),
    ]
    require(observations[0].outcome == "unknown" and
            observations[0].reason == "not_applicable" and observations[0].facts is None)
    require(observations[1].facts == {"status": "restricted"})
    report["observations"] = [o.model_dump(mode="json") for o in observations]
    denied = await tools.query_area_status(Identity(tenant_id="other", user_id=identity.user_id),
                                          {"area_id": refs["area_id"]})
    require(denied.reason == "access_denied" and denied.source is None and denied.facts is None)
    report["tool_cross_tenant_denied"] = denied.model_dump(mode="json")
    memory = MemoryStore(dsn, clock=lambda: now)
    await memory.initialize()
    source = fixture["feedback"] | {"source_ref": "synthetic-reuse-preference"}
    report["memory_source"] = await memory.feedback(identity, source)
    candidate = await memory.propose(identity, source["source_ref"], 1)
    report["memory_history"] = [candidate]
    save()
    require(await memory.list_active(identity) == [])
    mid = candidate["memory_id"]

    async def change(op, **kwargs):
        row = await memory.change(identity, mid, report["memory_history"][-1]["revision"],
                                  op, **kwargs)
        report["memory_history"].append(row)
        save()
        return row

    active = await change("confirm")
    fresh = MemoryStore(dsn, clock=lambda: now)
    require(await fresh.list_active(identity) == [active])
    report["memory_fresh_session_equal"] = True
    require(await fresh.list_active(Identity(tenant_id=identity.tenant_id, user_id="other")) == [])
    report["memory_other_user_empty"] = True
    try:
        await memory.change(identity, mid, 1, "delete")
    except MemoryConflict:
        report["memory_stale_revision_denied"] = True
    else:
        raise ValueError("Stale memory revision accepted")
    report["transfer"] = transfer(fixture, report["observations"],
                                   {active["key"]: active["value"]})
    await change("conflict")
    require(await memory.list_active(identity) == [])
    await memory.feedback(identity, source | {"version": 2, "value": "unknowns_first"})
    await change("correct", source_ref=source["source_ref"], source_version=2)
    require(await memory.list_active(identity) == [])
    await change("confirm")
    now += timedelta(days=2)
    require(await memory.list_active(identity) == [])
    report["memory_expired_hidden_without_mutation"] = True
    await change("expire")
    await change("delete")
    require(await memory.list_active(identity) == [])
    require(await memory.history(identity, mid) == report["memory_history"])
    report["budget_after"] = await ledger.snapshot()
    require(report["budget_before"] == report["budget_after"])
    report["model_request_delta"] = 0
    report["status"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        args.output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("Use a new evidence directory")
    report = {"status": "failed", "data_origin": "SYNTHETIC", "mode": "offline_existing_assets",
              "framework_mode": "Mem0_static_analysis_not_executed", "model_request_delta": None,
              "budget_before": None, "budget_after": None, "personal_evidence": "not_provided"}

    def save():
        (args.output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        asyncio.run(evaluate(args.output_dir, report, save), loop_factory=asyncio.SelectorEventLoop)
    except (Exception, KeyboardInterrupt) as exc:
        report["error_category"] = type(exc).__name__
    finally:
        save()
    summary = {k: report.get(k) for k in ("status", "error_category", "model_request_delta")}
    print(json.dumps(summary))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
