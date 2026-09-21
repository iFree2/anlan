"""Private loopback HTTP input adapter for the existing scoped FactTools."""
import asyncio
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from anlan.tools.http_client import ROUTES


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
