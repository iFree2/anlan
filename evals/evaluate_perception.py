"""Two synthetic event chains, real PG/BGE, optional two bounded P5 model requests."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.perception import PerceptionStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.perception_runtime import PerceptionRuntime
from anlan.interfaces.runtime import postgres_service
from anlan.knowledge.embeddings import LocalEmbeddings
from anlan.knowledge.store import KnowledgeStore
from anlan.llm.config import ModelConfig
from anlan.llm.perception import DeepSeekPerceptionModel, ScriptedPerceptionModel
from anlan.memory.store import MemoryStore
from anlan.tools.queries import FactTools
from anlan.workflows.event_contracts import SourceBinding, digest
from anlan.workflows.material_analysis import OfflineAnalyzer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "examples/synthetic/perception-v1"
IDENTITY = Identity(tenant_id="synthetic-p5-replay", user_id="safety-manager-demo")
MATERIAL = {
    "work_location_description": "SYNTHETIC：area-p5-demo台架",
    "work_object_description": "SYNTHETIC：P5独立演示试件",
    "work_method_description": "SYNTHETIC：worker-p5-001进行焊接",
    "attachment_description": "SYNTHETIC：P5试件示意图",
}


def chain_passes(row):
    return (
        row["review"]["result"]["status"] == "completed"
        and row["review"]["currentness"] == "current"
        and row["duplicate"]["review_id"] == row["review"]["review_id"]
        and row["feedback"]["feedback"]["decision"] == "needs_verification"
        and row["stale_after_revision"]["currentness"] == "stale_material"
        and row["revised"]["revision"] == row["material"]["revision"] + 1
        and row["follow_up"]["result"]["status"] == "completed"
        and row["follow_up"]["material_revision"] == row["revised"]["revision"]
        and row["follow_up"]["result"]["report"]["mode"] == "scripted_double"
        and row["raw_unchanged"]
    )


async def evaluate(args, report, save):
    fixture = json.loads((ROOT / "examples/synthetic/events-v1.json").read_text(encoding="utf-8"))
    now, dsn = datetime.fromisoformat(fixture["clock"]), database_url()
    clock = lambda: now  # noqa: E731
    await initialize_database(dsn)
    events, ledger = EventStore(dsn, clock=clock), BudgetLedger(dsn)
    await events.initialize()
    await PerceptionStore(dsn).initialize()
    memory = MemoryStore(dsn, clock=clock)
    await memory.initialize()
    knowledge = KnowledgeStore(dsn, await LocalEmbeddings.create(), clock=clock)
    await knowledge.initialize()
    documents = json.loads((DATA / "knowledge.json").read_text(encoding="utf-8"))
    for document in documents["documents"]:
        await knowledge.ingest(IDENTITY, document)
    refs = json.loads((DATA / "refs.json").read_text(encoding="utf-8"))
    report["fixtures_sha256"] = digest({"events": fixture, "knowledge": documents, "refs": refs})
    report["budget_before"] = await ledger.snapshot()
    save()

    async def cli(*command):
        # Read/feedback subprocesses have no model credentials or model options.
        env = os.environ | {"PYTHONIOENCODING": "utf-8"}
        env.pop("DEEPSEEK_API_KEY", None)
        process = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "anlan.interfaces.perception_cli",
                "--tenant",
                IDENTITY.tenant_id,
                "--user",
                IDENTITY.user_id,
                "--as-of",
                now.isoformat(),
                *map(str, command),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=40,
        )
        report["commands"].append({"command": command[0], "returncode": process.returncode})
        save()
        if process.returncode:
            raise ValueError("Read/feedback CLI failed")
        return json.loads(process.stdout)

    async with httpx.AsyncClient(follow_redirects=False) as client:
        for event in fixture["events"]:
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                material = await service.start(IDENTITY, MATERIAL)
            source = SourceBinding(
                identity=IDENTITY,
                source_id="p5-review-" + uuid4().hex,
                kind=event["kind"],
                object_ref=event["object_ref"],
                task_id=material["task_id"],
                revision=material["revision"],
                run_id=material["run_id"],
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(hours=1),
            )
            received = await events.receive(IDENTITY, source.source_id, event, source)
            row = {
                "kind": event["kind"],
                "material": material,
                "received": received,
                "request_id": report["experiment_id"] + "-" + event["kind"],
            }
            report["rows"].append(row)
            save()  # Persist task/receipt/request identifiers before any model request.
            model = ScriptedPerceptionModel()
            if args.mode == "deepseek":
                config = ModelConfig.from_env().model_copy(update={"max_requests": 1})
                model = DeepSeekPerceptionModel(config, client, ledger)
            runtime = PerceptionRuntime(
                dsn, FactTools(DATA / "facts", clock=clock), knowledge, memory, model, clock=clock
            )
            review = await runtime.review(
                IDENTITY, received["receipt_id"], refs, request_id=row["request_id"]
            )
            row["review"] = review
            save()
            row["duplicate"] = await runtime.review(
                IDENTITY, received["receipt_id"], refs, request_id=row["request_id"]
            )
            row["read_from_new_process"] = await cli("show", review["review_id"])
            row["feedback"] = None
            if review["result"]["status"] == "completed":
                row["feedback"] = await cli(
                    "feedback",
                    review["review_id"],
                    "--revision",
                    "1",
                    "--request-id",
                    "synthetic-feedback",
                    "--decision",
                    "needs_verification",
                )
            # Synthetic feedback is a replay action, never a claim that the user verified a scene.
            row["feedback_origin"] = "synthetic_replay_actor"
            async with postgres_service(dsn, OfflineAnalyzer()) as service:
                revised = await service.revise(
                    IDENTITY,
                    material["task_id"],
                    1,
                    {"work_method_description": "SYNTHETIC：变更为手工打磨，需重新核对"},
                    request_id="synthetic-condition-change",
                )
            row["revised"] = revised
            row["stale_after_revision"] = await runtime.get(IDENTITY, review["review_id"])
            new_source = source.model_copy(update={"revision": 2, "run_id": revised["run_id"]})
            new_event = event | {"event_id": event["event_id"] + "-revision2", "sequence": 2}
            follow_receipt = await events.receive(IDENTITY, source.source_id, new_event, new_source)
            runtime.model = (
                ScriptedPerceptionModel()
            )  # Follow-up is explicitly NOT another live call.
            row["follow_up"] = await runtime.review(
                IDENTITY, follow_receipt["receipt_id"], refs, request_id="scripted-recheck"
            )
            row["raw_unchanged"] = (await events.get(IDENTITY, received["receipt_id"]))[
                "raw"
            ] == event
            row["engineering_chain_passed"] = chain_passes(row)
            save()
    report["budget_after"] = await ledger.snapshot()
    owned_runs = {row["review"]["run_id"] for row in report["rows"]}
    report["requests_this_run"] = sum(
        a["run_id"] in owned_runs for a in report["budget_after"]["attempts"]
    )
    report["application_accepted"] = sum(
        row["review"]["result"]["status"] == "completed" for row in report["rows"]
    )
    report["engineering_chains_passed"] = sum(
        row["engineering_chain_passed"] for row in report["rows"]
    )
    expected = 2 if args.mode == "deepseek" else 0
    if report["requests_this_run"] != expected:
        raise ValueError("Unexpected model request count")
    report["status"] = "completed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=["scripted", "deepseek"], default="scripted")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new report path; historical evidence must be retained")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "failed",
        "data_origin": "SYNTHETIC",
        "work_package": "P5-WP02",
        "mode": args.mode,
        "exposure": "developer_seen",
        "experiment_id": uuid4().hex,
        "requests_this_run": 0,
        "rows": [],
        "commands": [],
    }

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        asyncio.run(evaluate(args, report, save), loop_factory=asyncio.SelectorEventLoop)
    except Exception as exc:
        report["error_category"] = type(exc).__name__
    finally:
        save()
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in [
                    "status",
                    "mode",
                    "requests_this_run",
                    "application_accepted",
                    "error_category",
                ]
            }
        )
    )
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
