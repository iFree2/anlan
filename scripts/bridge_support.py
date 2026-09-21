"""Local demo/test runtime; owns and cleans only the server and Java process it creates."""

import os
import secrets
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx

from anlan.interfaces.fact_http import create_fact_server
from anlan.tools.queries import FactTools

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def bridge_stack(directory, identity, now, build_dir):
    build_dir.mkdir(parents=True, exist_ok=True)
    compiled = subprocess.run(
        [
            "javac",
            "-encoding",
            "UTF-8",
            "-d",
            str(build_dir),
            str(ROOT / "integrations/java/AnlanFactApi.java"),
        ],
        capture_output=True,
        timeout=30,
    )
    if compiled.returncode:
        raise RuntimeError("Java API compilation failed")
    private_token, token = secrets.token_hex(24), secrets.token_hex(24)
    server = create_fact_server(identity, FactTools(directory, clock=lambda: now), private_token)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    worker.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    process = None
    try:
        process = subprocess.Popen(
            [
                "java",
                "-Dsun.net.httpserver.maxReqTime=3",
                "-cp",
                str(build_dir),
                "AnlanFactApi",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                **os.environ,
                "ANLAN_API_TOKEN": token,
                "ANLAN_BACKEND_TOKEN": private_token,
                "ANLAN_BACKEND_URL": f"http://127.0.0.1:{server.server_port}",
            },
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        ready = False
        with httpx.Client(trust_env=False, timeout=0.3) as client:
            for _ in range(50):
                if process.poll() is not None:
                    break
                try:
                    ready = client.get(url + "/health").status_code == 200
                except httpx.HTTPError:
                    pass
                if ready:
                    break
                time.sleep(0.1)
        if not ready:
            raise RuntimeError("Java API failed readiness check")
        yield SimpleNamespace(
            url=url,
            token=token,
            server=server,
            process=process,
            identity=identity,
            now=now,
            headers={
                "Authorization": "Bearer " + token,
                "X-Anlan-Tenant": identity.tenant_id,
                "X-Anlan-User": identity.user_id,
                "X-Anlan-As-Of": now.isoformat(),
            },
        )
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
