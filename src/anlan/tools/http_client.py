"""Loopback adapters only; existing FactTools retain all business rules and authority."""


import asyncio
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
