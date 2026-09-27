"""Real local HTTP, SSE disconnect and process restart; no ASGI transport substitute."""

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_events import NOW, OWNER, payload
from test_events_postgres import dsn, run, setup  # noqa: F401 -- PG fixture
from test_material_revisions import COMPLETE, PATCH
from test_perception_postgres import REFS
from test_service_api import TOKEN

pytestmark = pytest.mark.postgres


class Server:
    def __init__(self, dsn, directory):  # noqa: F811 -- shared fixture name
        _, _, binding = run(setup(dsn))
        self.source = binding.source_id
        config = {
            "schema_version": "local-service-v1",
            "as_of": NOW.isoformat(),
            "tokens": [{"token": TOKEN, "identity": OWNER.model_dump()}],
            "sources": [{"binding": binding.model_dump(mode="json"), "references": REFS}],
            "facts_dir": str(Path("examples/synthetic/facts-v1").resolve()),
            "embeddings_cache": str(Path(".runtime/embeddings").resolve()),
        }
        self.config = directory / "config.json"
        self.config.write_text(json.dumps(config), encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = os.environ | {"ANLAN_DATABASE_URL": dsn, "PYTHONIOENCODING": "utf-8"}
        self.env.pop("DEEPSEEK_API_KEY", None)
        self.directory, self.process, self.log = directory, None, None
        self.marker = directory / "model-entered"

    def start(self, *, slow=False):
        self.marker.unlink(missing_ok=True)
        args = [
            sys.executable,
            "-m",
            "anlan.interfaces.serve",
            "--config",
            str(self.config),
            "--port",
            str(self.port),
        ]
        if slow:
            code = """
import asyncio,sys,uvicorn
from pathlib import Path
from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig
from anlan.infrastructure.db import database_url
from anlan.llm.perception import ScriptedPerceptionModel
class Slow(ScriptedPerceptionModel):
 async def generate(self, context, run_id):
  Path(sys.argv[3]).write_text('entered')
  await asyncio.sleep(10)
  return await super().generate(context,run_id)
app=create_app(database_url(),ServiceConfig.from_file(sys.argv[1]),model_factory=Slow)
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=int(sys.argv[2]),access_log=False,log_level='warning'))
asyncio.run(server.serve(),loop_factory=asyncio.SelectorEventLoop)
"""
            args = [sys.executable, "-c", code, str(self.config), str(self.port), str(self.marker)]
        self.log = (self.directory / ("server-" + uuid4().hex + ".log")).open("wb")
        self.process = subprocess.Popen(args, stdout=self.log, stderr=self.log, env=self.env)
        deadline = time.monotonic() + 30
        with httpx.Client(trust_env=False, timeout=1) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError("Owned service exited before readiness; inspect test log")
                try:
                    if client.get(self.url + "/healthz").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
        raise AssertionError("Owned HTTP service did not become ready")

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.log is not None:
            self.log.close()

    def client(self):
        return httpx.Client(
            base_url=self.url,
            headers={"Authorization": "Bearer " + TOKEN},
            trust_env=False,
            timeout=20,
        )


def read_snapshot(response):
    event_id = None
    for line in response.iter_lines():
        if line.startswith("id: "):
            event_id = line[4:]
        if line.startswith("data: "):
            return event_id, json.loads(line[6:])
    raise AssertionError("No complete snapshot received")


def test_real_http_sse_disconnect_reconnect_and_server_restart(dsn, tmp_path):  # noqa: F811
    server = Server(dsn, tmp_path)
    try:
        server.start()
        with server.client() as client:
            request_id = uuid4().hex
            initial = client.post("/tasks", json={"request_id": request_id, "fields": COMPLETE})
            assert initial.status_code == 200
            task = initial.json()["task_id"]
            with client.stream("GET", f"/tasks/{task}/stream") as response:
                assert response.status_code == 200
                first_id, first = read_snapshot(response)
            assert first["revision"] == 1
            revised = client.post(
                f"/tasks/{task}/revise",
                json={"request_id": "revision", "expected_revision": 1, "fields": PATCH},
            )
            assert revised.status_code == 200
            with client.stream(
                "GET", f"/tasks/{task}/stream", headers={"Last-Event-ID": first_id}
            ) as response:
                next_id, snapshot = read_snapshot(response)
            assert next_id != first_id and snapshot["revision"] == 2
            server.stop()
            server.start()
            assert client.get("/tasks/by-request/" + request_id).json()["revision"] == 2
            with client.stream(
                "GET", f"/tasks/{task}/stream", headers={"Last-Event-ID": first_id}
            ) as response:
                restarted_id, restarted = read_snapshot(response)
            assert restarted_id == next_id and restarted == snapshot
            # Closing a subscription did not cancel or remove the business task.
            assert client.get(f"/tasks/{task}").json()["revision"] == 2
    finally:
        server.stop()


@pytest.mark.parametrize("stop", ["cancel", "restart"])
def test_review_disconnect_persistent_cancel_or_restart_recovery(dsn, tmp_path, stop):  # noqa: F811
    server = Server(dsn, tmp_path)
    try:
        server.start(slow=True)
        with server.client() as client, ThreadPoolExecutor(max_workers=1) as executor:
            receipt = client.post(f"/sources/{server.source}/events", json=payload()).json()[
                "receipt_id"
            ]
            path = f"/events/{receipt}/reviews"
            job = executor.submit(client.post, path, json={"request_id": "long-review"})
            deadline = time.monotonic() + 8
            while not server.marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.marker.exists()
            pending = None
            for _ in range(50):
                response = client.post(path, json={"request_id": "long-review"})
                if response.status_code == 200 and response.json()["result"] is None:
                    pending = response.json()
                    break
                time.sleep(0.05)
            assert pending is not None
            review_id = pending["review_id"]
            if stop == "cancel":
                assert client.post(f"/reviews/{review_id}/cancel").json()["cancel_requested"]
                assert job.result(timeout=5).json()["result"]["status"] == "cancelled"
            else:
                server.stop()
                with pytest.raises(httpx.HTTPError):
                    job.result(timeout=5)
                server.start()
                restored = client.post(f"/reviews/{review_id}/recover").json()
                assert restored["result"]["status"] == "interrupted"
                assert restored["result"]["report"]["model_resubmitted"] is False
            assert client.get(f"/events/{receipt}").json()["raw"]["alarm_state"] == "active"
    finally:
        server.stop()
