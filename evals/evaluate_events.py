"""Independent SYNTHETIC event clock; real PG and separate CLI processes, no model."""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from anlan.common.models import Identity
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.postgres import initialize_database
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.interfaces.runtime import postgres_service
from anlan.workflows.event_contracts import SourceBinding, digest
from anlan.workflows.material_analysis import OfflineAnalyzer

ROOT = Path(__file__).resolve().parents[1]


def replay_passes(rows):
    kinds = {"helmet_missing", "gas_abnormal"}
    return len(rows) == 2 and {r["kind"] for r in rows} == kinds and all(
        r["read_before_processing"] == r["received"]
        and r["received"]["result"] is None
        and r["processed"]["raw"] == r["received"]["raw"]
        and r["processed"]["raw"]["alarm_state"] == "active"
        and r["processed"]["result"]["status"] == "linked"
        and r["processed"]["result"]["task_id"] == r["material"]["task_id"]
        and r["processed"]["result"]["revision"] == r["material"]["revision"]
        and r["processed"]["result"]["run_id"] == r["material"]["run_id"]
        and r["duplicate"] == r["processed"] == r["read_after_processing"]
        and r["denied_read_returncode"] == 2 and r["material_unchanged"]
        for r in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new report path; historical evidence is immutable")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / "examples/synthetic/events-v1.json").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(data["clock"])
    identity = Identity(tenant_id="synthetic-p5-replay", user_id="safety-manager-demo")
    report = {"status": "failed", "work_package": "P5-WP01", "data_origin": "SYNTHETIC",
              "mode": "engineering_replay", "requests_this_run": 0,
              "clock_mode": "simulated", "as_of": data["clock"], "fixtures_sha256": digest(data),
              "rows": [], "commands": []}

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def cli(*command, user=identity.user_id, expected=0):
        result = subprocess.run([sys.executable, "-m", "anlan.interfaces.events_cli",
            "--tenant", identity.tenant_id, "--user", user, "--as-of", now.isoformat(),
            *map(str, command)], cwd=ROOT, capture_output=True, encoding="utf-8", timeout=40,
            env=os.environ | {"PYTHONIOENCODING": "utf-8"})
        report["commands"].append({"command": command[0], "returncode": result.returncode})
        save()
        if result.returncode != expected:
            raise ValueError("CLI failed; inspect retained command metadata")
        return json.loads(result.stdout) if expected == 0 else result.returncode

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        dsn = database_url()
        ledger = BudgetLedger(dsn)
        runner.run(initialize_database(dsn))
        runner.run(EventStore(dsn).initialize())
        report["budget_before"] = runner.run(ledger.snapshot())
        try:
            for event in data["events"]:
                async def new_task():
                    async with postgres_service(dsn, OfflineAnalyzer()) as service:
                        return await service.start(identity, DEMO_FIELDS)
                material = runner.run(new_task())
                source = SourceBinding(identity=identity, source_id="p5-" + uuid4().hex,
                    kind=event["kind"], object_ref=event["object_ref"], task_id=material["task_id"],
                    revision=material["revision"], run_id=material["run_id"],
                    valid_from=now - timedelta(minutes=1), valid_until=now + timedelta(hours=1))
                config_path = args.output.with_suffix("." + event["kind"] + ".binding.json")
                body_path = args.output.with_suffix("." + event["kind"] + ".body.json")
                config_path.write_text(source.model_dump_json(indent=2), encoding="utf-8")
                body_path.write_text(json.dumps(event, indent=2), encoding="utf-8")
                received = cli("receive", "--source", source.source_id,
                               "--binding", config_path, "--body", body_path)
                key = received["receipt_id"]
                row = {"kind": event["kind"], "material": material, "received": received,
                       "read_before_processing": cli("show", key),
                       "processed": cli("process", key),
                       "duplicate": cli("receive", "--source", source.source_id,
                                        "--binding", config_path, "--body", body_path),
                       "read_after_processing": cli("show", key),
                       "denied_read_returncode": cli("show", key, user="stranger", expected=2)}
                async def unchanged():
                    async with postgres_service(dsn, OfflineAnalyzer()) as service:
                        return await service.get(identity, material["task_id"]) == material
                row["material_unchanged"] = runner.run(unchanged())
                report["rows"].append(row)
                save()
            report["budget_after"] = runner.run(ledger.snapshot())
            if replay_passes(report["rows"]) and report["budget_before"] == report["budget_after"]:
                report["status"] = "passed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({"status": report["status"], "rows": len(report["rows"]),
                      "commands": len(report["commands"])}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
