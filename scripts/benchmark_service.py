"""Small owned localhost service experiment; all failures remain in latency samples."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import socket
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import httpx

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

ROOT = Path(__file__).resolve().parents[1]


def stop_owned(process):
    """Bound cleanup to this exact Popen; never enumerate or stop unrelated processes."""
    result = {"owned_process_stopped": False, "forced_stop": False}
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                result["forced_stop"] = True
                process.kill()
                process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["cleanup_error_category"] = type(exc).__name__
    finally:
        result["owned_process_stopped"] = process.poll() is not None
    return result


async def measure(client, path, expected, concurrency):
    if concurrency not in (1, 4, 8):
        raise ValueError("Use a predeclared small concurrency")
    semaphore = asyncio.Semaphore(concurrency)

    async def once(index):
        async with semaphore:
            started = perf_counter()
            row = {"index": index, "passed": False, "status_code": None}
            try:
                response = await client.get(path)
                row["status_code"] = response.status_code
                row["passed"] = response.status_code == 200 and response.json() == expected
            except (httpx.HTTPError, ValueError) as exc:
                row["error_category"] = type(exc).__name__
            row["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
            return row

    started = perf_counter()
    samples = await asyncio.gather(*(once(i) for i in range(24)))
    elapsed = perf_counter() - started
    values = sorted(s["elapsed_ms"] for s in samples)
    succeeded = sum(s["passed"] for s in samples)
    return {"concurrency": concurrency, "samples": samples, "succeeded": succeeded,
            "failed": 24 - succeeded, "passed": succeeded == 24,
            "wall_ms": round(elapsed * 1000, 3), "requests_per_second": round(24 / elapsed, 2),
            "p50_ms": statistics.median(values), "p95_ms": values[math.ceil(0.95 * 24) - 1],
            "max_ms": values[-1], "latency_population": "all_requests_including_failures",
            "queue_wait": "excluded_from_per_request_included_in_group_wall_time"}


async def run(args, report, save):
    config = json.loads(args.config.read_text(encoding="utf-8"))
    token = config["tokens"][0]["token"]
    task = config["sources"][0]["binding"]["task_id"]
    ledger = BudgetLedger(database_url())
    report["budget_before"] = await ledger.snapshot()
    report["package_files"] = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "src/anlan").rglob("*")
        if p.is_file() and p.suffix in {".py", ".sql", ".json", ".md"}
    }
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env["PYTHONIOENCODING"] = "utf-8"
    with args.output.with_suffix(".server.log").open("xb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "anlan.interfaces.serve", "--config",
             str(args.config.resolve()), "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                                         timeout=10) as client:
                deadline = perf_counter() + 30
                while True:
                    if process.poll() is not None or perf_counter() >= deadline:
                        raise ValueError("Owned service readiness failed")
                    try:
                        if (await client.get("/healthz", timeout=1)).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
                path = f"/tasks/{task}"
                report["unauthorized_status"] = (await client.get(path)).status_code
                client.headers["Authorization"] = "Bearer " + token
                response = await client.get(path)
                response.raise_for_status()
                expected = response.json()
                report["groups"] = []
                for concurrency in (1, 4, 8):
                    report["groups"].append(await measure(client, path, expected, concurrency))
                    save()
        finally:
            report.update(await asyncio.to_thread(stop_owned, process))
            if not report["owned_process_stopped"]:
                raise ValueError("Owned service cleanup failed")
    report["budget_after"] = await ledger.snapshot()
    if (report["budget_before"] != report["budget_after"]
            or report["unauthorized_status"] != 401
            or not all(g["passed"] for g in report["groups"])):
        raise ValueError("Reliability experiment has failures")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = {"status": "failed", "data_origin": "SYNTHETIC", "model_requests": 0,
              "scope": "warm_localhost_material_snapshot_reads_not_model_or_production_SLA"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        def save():
            stream.seek(0)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()
        try:
            asyncio.run(run(args, report, save), loop_factory=asyncio.SelectorEventLoop)
            report["status"] = "passed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        finally:
            save()
    print(json.dumps({"status": report["status"], "model_requests": 0,
                      "groups": [{k: g[k] for k in ("concurrency", "failed", "p50_ms", "p95_ms")}
                                 for g in report.get("groups", [])]}))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
