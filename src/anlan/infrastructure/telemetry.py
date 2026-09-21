"""既有JSONL事件到本地OTLP/HTTP的薄适配；属性白名单，无重试或外网目的地。"""

import hashlib
import json
import math
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import urlsplit

import httpx

ROOT_EVENTS = {
    "analysis_finished",
    "facts_finished",
    "tool_loop_finished",
    "knowledge_query_finished",
}
EVENTS = ROOT_EVENTS | {"tool_finished", "model_step_finished", "agent_tool_finished"}
ATTRIBUTES = {
    "task_id",
    "run_id",
    "correlation_id",
    "revision",
    "status",
    "mode",
    "source_run_id",
    "event",
    "tool",
    "call_id",
    "object_id",
    "outcome",
    "reason",
    "error",
    "step",
    "model_step",
    "stop_reason",
    "model_steps",
    "tool_calls",
    "attempt_id",
    "attempt_status",
    "data_origin",
    "model",
    "prompt_version",
    "semantic_status",
    "executed",
    "scenario",
}
SOURCE_KEYS = {
    "resource",
    "version",
    "sha256",
    "record_id",
    "observed_at",
    "valid_from",
    "valid_until",
    "doc_id",
    "chunk_id",
    "source",
    "content_hash",
    "document_hash",
}


def trace_id(run_id: str, *, archived: bool = False) -> str:
    prefix = "archive:" if archived else "trace:"
    return hashlib.sha256((prefix + run_id).encode()).hexdigest()[:32]


def root_span_id(run_id: str) -> str:
    return hashlib.sha256(("root:" + run_id).encode()).hexdigest()[:16]


def attribute(key, value):
    if type(value) is bool:
        encoded = {"boolValue": value}
    elif type(value) is int:
        encoded = {"intValue": str(value)}
    else:
        encoded = {"stringValue": str(value)[:8192]}
    return {"key": key, "value": encoded}


def payload_for(record: dict, *, archived: bool = False) -> dict:
    event = record["event"]
    if event not in EVENTS:
        raise ValueError("unsupported trace event")
    run_id = record["run_id"]
    moment = datetime.fromisoformat(record["timestamp"])
    if moment.tzinfo is None:
        raise ValueError("trace time must be timezone-aware")
    delta = moment - datetime(1970, 1, 1, tzinfo=UTC)
    end_ns = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    elapsed = record.get("elapsed_ms")
    duration_known = type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0
    duration_ns = int(elapsed * 1_000_000) if duration_known else 0
    attrs = [
        attribute("anlan." + key, record[key])
        for key in sorted(ATTRIBUTES)
        if record.get(key) is not None and type(record[key]) in (str, int, bool)
    ]
    attrs.extend(
        [
            attribute("anlan.duration_recorded", duration_known),
            attribute("anlan.recording_mode", "archived_import" if archived else "live_event"),
        ]
    )
    sources = record.get("source") or []
    sources = [sources] if isinstance(sources, dict) else sources
    safe_sources = [
        {
            k: value
            for k, value in source.items()
            if k in SOURCE_KEYS and type(value) in (str, int, bool)
        }
        for source in sources
        if isinstance(source, dict)
    ]
    if safe_sources:
        attrs.append(attribute("anlan.sources", json.dumps(safe_sources, ensure_ascii=False)))
    usage = record.get("usage") or {}
    if not isinstance(usage, dict):
        raise ValueError("usage metadata must be an object")
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(name)
        if type(value) is int and value >= 0:
            attrs.append(attribute("anlan.usage." + name, value))
    failed = (
        bool(record.get("error"))
        or record.get("outcome") == "error"
        or (event == "tool_loop_finished" and record.get("stop_reason") != "completed")
    )
    is_root = event in ROOT_EVENTS
    identity = ":".join(
        str(record.get(key, ""))
        for key in ("run_id", "event", "call_id", "tool", "step", "timestamp")
    )
    span = {
        "traceId": trace_id(run_id, archived=archived),
        "spanId": root_span_id(run_id)
        if is_root
        else hashlib.sha256(identity.encode()).hexdigest()[:16],
        "name": ("tool." + record["tool"]) if record.get("tool") and not is_root else event,
        "kind": 1,
        "startTimeUnixNano": str(end_ns - duration_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attrs,
        "status": {"code": 2 if failed else 1},
    }
    if not is_root:
        span["parentSpanId"] = root_span_id(run_id)
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        attribute("service.name", "anlan-2"),
                        attribute("service.namespace", "synthetic-local"),
                    ]
                },
                "scopeSpans": [
                    {"scope": {"name": "anlan.jsonl", "version": "otlp-bridge-v1"}, "spans": [span]}
                ],
            }
        ]
    }


class LocalOtlpExporter:
    def __init__(self, endpoint: str, *, client: httpx.Client | None = None):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/v1/traces"
            or parsed.port is None
        ):
            raise ValueError("OTLP endpoint must be a credential-free local HTTP traces endpoint")
        self.endpoint = endpoint
        self.client = client

    def export(self, record: dict, *, archived: bool = False) -> bool:
        try:
            payload = payload_for(record, archived=archived)
            if len(json.dumps(payload, ensure_ascii=False).encode()) > 32768:
                return False
            if self.client is not None:
                return self._send(self.client, payload)
            with httpx.Client(timeout=0.3, follow_redirects=False, trust_env=False) as client:
                return self._send(client, payload)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            return False

    def _send(self, client, payload):
        started = perf_counter()
        with client.stream(
            "POST", self.endpoint, json=payload, timeout=0.3, follow_redirects=False
        ) as response:
            if response.status_code != 200 or perf_counter() - started > 0.3:
                return False
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 4096 or perf_counter() - started > 0.3:
                    return False
        result = json.loads(body)
        return isinstance(result, dict) and not result.get("partialSuccess")
