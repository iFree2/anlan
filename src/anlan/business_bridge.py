"""Loopback adapters only; existing FactTools retain all business rules and authority."""

import asyncio
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx

from anlan.tools.contracts import AreaQuery, ToolResult, WorkerQuery
from anlan.tools.queries import MESSAGES

ROUTES = {
    "query_worker_qualification": "/api/worker-qualification",
    "query_area_status": "/api/area-status",
}
SCHEMAS = {"query_worker_qualification": WorkerQuery, "query_area_status": AreaQuery}


def validate_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise ValueError("Only a configured credential-free loopback origin is allowed")
    return url.rstrip("/")


def failure(tool, parameters, now, reason):
    return ToolResult(
        tool=tool,
        object_id=parameters.get(
            "worker_id" if tool == "query_worker_qualification" else "area_id"
        ),
        queried_at=now,
        outcome="error",
        reason=reason,
        message=MESSAGES[reason],
        elapsed_ms=0,
    )


class HttpFactClient:
    def __init__(self, url, token, now, *, identity, client):
        self.url = validate_url(url)
        self.token, self.now, self.client = token, now, client
        self.identity = identity.model_copy(deep=True)

    async def call(self, tool, parameters):
        if tool not in ROUTES:
            raise ValueError("Tool not allowed")
        try:
            SCHEMAS[tool].model_validate(parameters)
        except ValueError:
            return failure(tool, parameters, self.now, "invalid_parameters")
        try:
            async with asyncio.timeout(4):
                async with self.client.stream(
                    "POST",
                    self.url + ROUTES[tool],
                    json=parameters,
                    headers={
                        "Authorization": "Bearer " + self.token,
                        "X-Anlan-Tenant": self.identity.tenant_id,
                        "X-Anlan-User": self.identity.user_id,
                        "X-Anlan-As-Of": self.now.isoformat(),
                    },
                    timeout=3,
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        reason = {401: "access_denied", 504: "timeout"}.get(
                            response.status_code, "data_error"
                        )
                        return failure(tool, parameters, self.now, reason)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ValueError("Oversized tool result")
            value = ToolResult.model_validate_json(body)
            expected_id = parameters.get("worker_id", parameters.get("area_id"))
            if value.tool != tool or value.object_id != expected_id or value.queried_at != self.now:
                raise ValueError("Tool result binding mismatch")
            return value
        except (TimeoutError, httpx.TimeoutException):
            return failure(tool, parameters, self.now, "timeout")
        except (httpx.HTTPError, ValueError):
            return failure(tool, parameters, self.now, "data_error")


def create_fact_server(identity, tools, token, port=0):
    if len(token) < 16:
        raise ValueError("A private generated adapter token is required")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # No tokens, identities or payloads in HTTP access logs.

        def reply(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            self.connection.settimeout(3)
            authorization = self.headers.get_all("Authorization", [])
            if len(authorization) != 1 or not hmac.compare_digest(
                authorization[0], "Bearer " + token
            ):
                return self.reply(401, {"error": "unauthorized"})
            expected = {
                "X-Anlan-Tenant": identity.tenant_id,
                "X-Anlan-User": identity.user_id,
                "X-Anlan-As-Of": tools.clock().isoformat(),
            }
            if any(self.headers.get_all(key, []) != [value] for key, value in expected.items()):
                return self.reply(401, {"error": "scope_mismatch"})
            tool = next((key for key, path in ROUTES.items() if path == self.path), None)
            if tool is None:
                return self.reply(404, {"error": "not_found"})
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                    return self.reply(400, {"error": "invalid_body"})
                length = int(lengths[0])
                if not 0 <= length <= 4096:
                    return self.reply(413, {"error": "body_too_large"})
                parameters = json.loads(self.rfile.read(length))
                if not isinstance(parameters, dict):
                    return self.reply(400, {"error": "invalid_body"})
                result = asyncio.run(getattr(tools, tool)(identity, parameters))
                return self.reply(200, result.model_dump(mode="json"))
            except Exception:
                return self.reply(400, {"error": "invalid_request"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
