import importlib.util
from pathlib import Path

import httpx
import pytest


def smoke_module():
    path = Path("scripts/smoke_conversation.py")
    spec = importlib.util.spec_from_file_location("smoke_conversation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_rejects_live_service_before_any_post():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/console/api/info":
            return httpx.Response(200, json={"model_mode": "deepseek_live"})
        return httpx.Response(500)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as client:
        with pytest.raises(ValueError, match="scripted_double"):
            smoke_module().run_smoke(client)

    assert [request.method for request in requests] == ["GET", "GET"]
    assert all(request.method != "POST" for request in requests)
