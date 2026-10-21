"""Run a scripted conversation smoke against an already running HTTP process."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_smoke(client):
    """Exercise the HTTP boundary after proving the target is a scripted service."""
    require(client.get("/healthz").status_code == 200, "health check failed")
    info = client.get("/console/api/info").raise_for_status().json()
    if info.get("model_mode") != "scripted_double":
        raise ValueError("conversation smoke requires model_mode=scripted_double")

    checks = {}
    created = client.post(
        "/conversations", json={"request_id": f"smoke-{uuid4().hex}"}
    ).raise_for_status().json()
    conversation_id = created["conversation_id"]

    def send(text, request_id=None):
        nonlocal created
        request_id = request_id or f"smoke-{uuid4().hex}"
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "request_id": request_id,
                "expected_revision": created["revision"],
                "text": text,
            },
        ).raise_for_status()
        created = response.json()
        return created, request_id

    candidate, _ = send("明天去罐区补焊")
    require(candidate["status"] == "pending_confirmation", "candidate not pending")
    require(candidate["active_task_id"] is None, "task created before confirmation")
    checks["no_task_before_confirmation"] = True

    active, _ = send("确认申请")
    task_id = active["active_task_id"]
    require(task_id and active["status"] == "active_hot_work", "task not created")
    task_revision = active["task_projection"]["revision"]
    checks["confirmed_task_created"] = True

    chat, chat_request = send("电焊和气焊有什么区别？")
    require(chat["active_task_id"] == task_id, "chat lost active task")
    require(chat["task_projection"]["revision"] == task_revision, "chat mutated task")
    checks["chat_zero_business_writes"] = True

    replay = client.post(
        f"/conversations/{conversation_id}/messages",
        json={
            "request_id": chat_request,
            "expected_revision": active["revision"],
            "text": "电焊和气焊有什么区别？",
        },
    ).raise_for_status().json()
    require(replay == chat, "idempotent replay changed result")
    checks["idempotent_replay"] = True

    refreshed = client.get(f"/conversations/{conversation_id}").raise_for_status().json()
    require(refreshed["active_task_id"] == task_id, "refresh lost task binding")
    require(refreshed["revision"] == chat["revision"], "refresh changed revision")
    checks["cross_process_refresh"] = True
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.environ.get("ANLAN_SMOKE_TOKEN"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if not args.token:
        parser.error("--token or ANLAN_SMOKE_TOKEN is required")

    report = {
        "schema_version": "conversation-smoke-v1",
        "status": "failed",
        "data_origin": "SYNTHETIC",
        "model_mode": "scripted_double",
        "live_provider_requests": 0,
        "checks": {},
    }
    try:
        headers = {"Authorization": f"Bearer {args.token}"}
        with httpx.Client(base_url=args.base_url, headers=headers, timeout=45) as client:
            report["checks"] = run_smoke(client)
            report["status"] = "passed"
    except Exception as error:
        report["failure_type"] = type(error).__name__
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
