"""Isolated wheel interpreter, real HTTP/SSE and restart against persistent synthetic PG."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

ROOT = Path(__file__).resolve().parents[1]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def snapshot(response):
    require(response.status_code == 200, "SSE status")
    identifier = None
    for line in response.iter_lines():
        if line.startswith("id: "):
            identifier = line[4:]
        if line.startswith("data: "):
            require(identifier is not None, "SSE cursor missing")
            return {"id": identifier, "value": json.loads(line[6:])}
    raise ValueError("SSE snapshot missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), "Use a new evidence path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    require(
        len(config["sources"]) == 2
        and {s["binding"]["kind"] for s in config["sources"]} == {"helmet_missing", "gas_abnormal"},
        "Both synthetic event types are required",
    )
    headers = {"Authorization": "Bearer " + config["tokens"][0]["token"]}
    report = {
        "status": "failed",
        "data_origin": "SYNTHETIC",
        "requests_this_run": 0,
        "rows": [],
        "restarts": 0,
        "credentials_recorded": False,
    }

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def budget():
        return asyncio.run(
            BudgetLedger(database_url()).snapshot(), loop_factory=asyncio.SelectorEventLoop
        )

    process, log = None, None

    def stop():
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if log is not None:
            log.close()

    @contextmanager
    def workspace():
        with tempfile.TemporaryDirectory(prefix="anlan-clean-http-") as directory:
            try:
                yield directory
            finally:
                stop()  # Stop the owned server before Windows removes its working directory.

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("PYTHONPATH", None)
    try:
        report["budget_before"] = budget()
        with workspace() as directory:
            probe = subprocess.run(
                [
                    str(args.python.resolve()),
                    "-I",
                    "-c",
                    "import anlan,sys,json,pathlib,hashlib;"
                    "root=pathlib.Path(anlan.__file__).parent;"
                    "files={'src/anlan/'+p.relative_to(root).as_posix():"
                    "hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') "
                    "if p.is_file() and p.suffix in {'.py','.json','.sql','.md'}};"
                    "print(json.dumps({'package':anlan.__file__,'prefix':sys.prefix,"
                    "'package_files':files}))",
                ],
                cwd=directory,
                capture_output=True,
                timeout=20,
                env=env,
            )
            require(probe.returncode == 0, "Isolated import failed")
            report["interpreter"] = json.loads(probe.stdout)
            require("site-packages" in report["interpreter"]["package"], "Imported source checkout")
            require(
                Path(report["interpreter"]["prefix"]) in args.python.resolve().parents,
                "Interpreter prefix mismatch",
            )

            def start(index):
                nonlocal process, log
                log = args.output.with_suffix(f".server-{index}.log").open("xb")
                process = subprocess.Popen(
                    [
                        str(args.python.resolve()),
                        "-I",
                        "-m",
                        "anlan.interfaces.serve",
                        "--config",
                        str(args.config.resolve()),
                        "--port",
                        str(port),
                    ],
                    cwd=directory,
                    env=env,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                deadline = time.monotonic() + 30
                with httpx.Client(trust_env=False, timeout=1) as client:
                    while time.monotonic() < deadline:
                        require(process.poll() is None, "Service exited during startup")
                        try:
                            if client.get(url + "/healthz").status_code == 200:
                                return
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                raise ValueError("Service readiness deadline")

            start(0)
            fixtures = json.loads(
                (ROOT / "examples/synthetic/events-v1.json").read_text(encoding="utf-8")
            )["events"]
            with httpx.Client(base_url=url, headers=headers, trust_env=False, timeout=30) as client:
                report["ready"] = client.get("/readyz").json()
                for source in config["sources"]:
                    binding = source["binding"]
                    event = next(e for e in fixtures if e["kind"] == binding["kind"])
                    received = client.post(f"/sources/{binding['source_id']}/events", json=event)
                    require(received.status_code == 200, "Receipt failed")
                    receipt = received.json()["receipt_id"]
                    response = client.post(
                        f"/events/{receipt}/reviews", json={"request_id": "clean-review"}
                    )
                    require(response.status_code == 200, "Review failed")
                    review = response.json()
                    require(review["result"]["status"] == "completed", "Candidate unavailable")
                    require(
                        review["result"]["report"]["requests_this_run"] == 0, "Unexpected request"
                    )
                    key = review["review_id"]
                    with client.stream("GET", f"/reviews/{key}/stream") as stream:
                        first = snapshot(stream)
                    feedback = client.post(
                        f"/reviews/{key}/feedback",
                        json={
                            "request_id": "feedback",
                            "expected_revision": 1,
                            "decision": "needs_verification",
                        },
                    )
                    require(feedback.status_code == 200, "Feedback failed")
                    with client.stream(
                        "GET", f"/reviews/{key}/stream", headers={"Last-Event-ID": first["id"]}
                    ) as stream:
                        updated = snapshot(stream)
                    require(
                        updated["id"] != first["id"] and updated["value"]["revision"] == 2,
                        "Reconnect did not observe durable feedback",
                    )
                    raw = client.get(f"/events/{receipt}").json()["raw"]
                    require(raw == event and raw["alarm_state"] == "active", "Raw alarm changed")
                    report["rows"].append(
                        {
                            "kind": event["kind"],
                            "receipt_id": receipt,
                            "review": review,
                            "feedback": feedback.json(),
                            "snapshot": updated,
                            "raw_unchanged": True,
                            "feedback_origin": "synthetic_replay_actor",
                        }
                    )
                    save()
                stop()
                start(1)
                report["restarts"] = 1
                for row in report["rows"]:
                    key = row["review"]["review_id"]
                    with client.stream("GET", f"/reviews/{key}/stream") as stream:
                        restored = snapshot(stream)
                    require(restored == row["snapshot"], "Restart changed durable snapshot")
                    row["restart_snapshot_equal"] = True
            report["budget_after"] = budget()
            require(report["budget_before"] == report["budget_after"], "Budget changed")
            report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error_category"] = type(exc).__name__
    finally:
        stop()
        report["owned_process_stopped"] = process is None or process.poll() is not None
        save()
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in ("status", "restarts", "owned_process_stopped", "error_category")
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
