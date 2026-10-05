"""Reproduce bounded synthetic chains; no live mode, credentials file, or hidden retry."""

import argparse
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import anlan
from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

ROOT = Path(__file__).resolve().parents[1]
PROCESS_TIMEOUT_SECONDS = 180

# The child cannot import project code or spawn descendants until its job is attached.
BOOTSTRAP = """
import sys,runpy
from pathlib import Path
if sys.stdin.buffer.readline() != b'go\\n':
    raise SystemExit(2)
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'src'))
import anlan
if Path(anlan.__file__).resolve().parent != root / 'src/anlan':
    raise SystemExit(2)
args = sys.argv[2:]
if args[0] == '-m':
    sys.argv = args[1:]
    runpy.run_module(args[1], run_name='__main__', alter_sys=True)
else:
    sys.argv = args
    runpy.run_path(args[0], run_name='__main__')
"""


def fingerprint():
    paths = [p for folder in ("src/anlan", "scripts", "evals", "examples/synthetic")
             for p in (ROOT / folder).rglob("*")
             if p.is_file() and p.suffix in {".py", ".json", ".sql", ".md"}]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def budget_snapshot():
    return asyncio.run(BudgetLedger(database_url()).snapshot(),
                       loop_factory=asyncio.SelectorEventLoop)


def require(condition):
    if not condition:
        raise ValueError("Takeover evidence contract failed")


def validate_step(name, report):
    require("error_category" not in report)
    if name == "materials":
        require(report["status"] == "passed" and report["mode"] == "offline")
        require(len(report["sql_runs"]) == 3 and len(report["commands"]) == 9)
        return {"material_revisions": 3, "cli_commands": 9}
    if name == "perception":
        require(report["status"] == "completed" and report["mode"] == "scripted")
        require(report["requests_this_run"] == 0)
        require(len(report["rows"]) == 2 and
                {r["kind"] for r in report["rows"]} == {"helmet_missing", "gas_abnormal"})
        require(all(r["engineering_chain_passed"] for r in report["rows"]))
        return {"engineering_chains": 2, "model_mode": "scripted_double"}
    require(report["status"] == "completed" and report["model_requests"] == 0)
    rows = report["rows"]
    if name == "inspect":
        require(len(rows) == 11)
        return {"frozen_records": 11, "new_badcases_mined": 0}
    expected_size, missing = {"dev": (6, 2), "holdout": (5, 0)}[name]
    require(len(rows) == expected_size and all(r["matches_expected"] for r in rows))
    require(report["matches_expected"] == expected_size)
    require(sum(r["actual"] == "not_replayable" for r in rows) == missing)
    require(report["not_replayable"] == missing)
    return {"contract_matches": expected_size, "recorded_outputs_replayed": expected_size - missing,
            "not_replayable": missing, "new_model_successes": 0}


def execute(argv):
    env = os.environ | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                        "PYTHONPATH": str(ROOT / "src")}
    for key in ("DEEPSEEK_API_KEY", "ANLAN_OTLP_ENDPOINT"):
        env.pop(key, None)
    job, process = None, None
    if os.name == "nt":
        # pywin32 is already locked as MCP's Windows dependency; no runtime installation.
        import win32api
        import win32job

        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", BOOTSTRAP, str(ROOT), *argv], cwd=ROOT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        if job is not None:
            handle = win32api.OpenProcess(0x0101, False, process.pid)  # SET_QUOTA | TERMINATE
            try:
                win32job.AssignProcessToJobObject(job, handle)
            finally:
                handle.Close()
        process.communicate(input=b"go\n", timeout=PROCESS_TIMEOUT_SECONDS)
        return process.returncode
    finally:
        try:
            if job is not None:
                win32job.TerminateJobObject(job, 1)
                deadline = time.monotonic() + 10
                while win32job.QueryInformationJobObject(
                    job, win32job.JobObjectBasicAccountingInformation
                )["ActiveProcesses"]:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Owned job cleanup deadline")
                    time.sleep(0.01)
            elif process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            if job is not None:
                job.Close()
            if process is not None:
                if process.poll() is None:
                    process.kill()  # Also handles failure to attach the waiting child.
                process.wait(timeout=10)
                process.stdin.close()


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "takeover-demo-v1", "status": "failed",
              "created_at": datetime.now(UTC).isoformat(), "data_origin": "SYNTHETIC",
              "model_mode": "offline_and_scripted_double", "personal_evidence": "not_provided",
              "budget_before": None, "budget_after": None, "model_request_delta": None,
              "steps": [], "failed_stage": None}

    def save():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")

    stage = "source_origin"
    try:
        require(Path(anlan.__file__).resolve().parent == ROOT / "src/anlan")
        report["imported_package"] = str(Path(anlan.__file__).resolve())
        stage = "fingerprint_before"
        report["source_before"] = fingerprint()
        save()
        stage = "budget_before"
        report["budget_before"] = budget_snapshot()
        save()
        quality = ["-m", "anlan.interfaces.quality_cli"]
        manifest = ["--manifest", "evals/quality-v1/manifest.json", "--root", str(ROOT)]
        commands = [
            ("materials", ["scripts/smoke_postgres.py"]),
            ("perception", ["evals/evaluate_perception.py", "--mode", "scripted"]),
            ("inspect", [*quality, "inspect", *manifest]),
            ("dev", [*quality, "replay", *manifest, "--split", "dev"]),
            ("holdout", [*quality, "replay", *manifest, "--split", "holdout"]),
        ]
        for stage, argv in commands:
            target = output / (stage + ".json")
            command = [*argv, "--output", str(target)]
            step = {"name": stage, "argv": command, "status": "started"}
            report["steps"].append(step)
            save()
            step["exit_code"] = execute(command)
            require(step["exit_code"] == 0)
            step["checks"] = validate_step(stage, json.loads(target.read_text(encoding="utf-8")))
            step["status"] = "passed"
            save()
        stage = "fingerprint_after"
        report["source_after"] = fingerprint()
        require(report["source_before"] == report["source_after"])
        stage = "budget_after"
        report["budget_after"] = budget_snapshot()
        report["model_request_delta"] = (report["budget_after"]["total_reserved"] -
                                         report["budget_before"]["total_reserved"])
        require(report["budget_before"] == report["budget_after"])
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as exc:
        report["failed_stage"] = stage
        report["error_category"] = type(exc).__name__
    finally:
        if report["budget_after"] is None:
            try:
                report["budget_after"] = budget_snapshot()
            except Exception as exc:
                report["final_budget_error"] = type(exc).__name__
        # A failed/unavailable final read is unknown, never a zero request assertion.
        if report["budget_before"] is not None and report["budget_after"] is not None:
            report["model_request_delta"] = (report["budget_after"]["total_reserved"] -
                                             report["budget_before"]["total_reserved"])
        report["artifacts"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(output.iterdir())
                               if p.is_file() and p.name != "report.json"}
        save()
    print(json.dumps({k: report[k] for k in ("status", "failed_stage", "model_request_delta")}))
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.output_dir)
    except FileExistsError:
        parser.error("Use a new directory; previous evidence is immutable")


if __name__ == "__main__":
    raise SystemExit(main())
