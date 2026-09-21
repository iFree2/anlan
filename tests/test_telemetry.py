import json

import httpx
import pytest

from anlan.common.models import Identity
from anlan.infrastructure.trace import JsonlTrace
from anlan.interfaces.cli import DEMO_FIELDS
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.service import WorkflowService

RECORD = {
    "event": "agent_tool_finished",
    "timestamp": "2026-09-20T12:00:00+00:00",
    "task_id": "task-1",
    "run_id": "run-1",
    "correlation_id": "correlation-1",
    "revision": 1,
    "status": "awaiting_review",
    "tool": "query_knowledge",
    "call_id": "call-1",
    "outcome": "ok",
    "reason": None,
    "elapsed_ms": 12.5,
    "mode": "scripted_double",
    "fields": {"secret": "material-sentinel"},
    "reasoning_content": "reasoning-sentinel",
    "source": [
        {
            "doc_id": "watcher",
            "version": 1,
            "chunk_id": "chunk-1",
            "content_hash": "a" * 64,
            "quote": "quote-sentinel",
        }
    ],
}


def test_otlp_payload_has_stable_parent_ids_and_excludes_raw_content():
    from anlan.infrastructure.telemetry import payload_for, root_span_id, trace_id

    payload = payload_for(RECORD)
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == trace_id("run-1")
    assert span["parentSpanId"] == root_span_id("run-1")
    assert int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"]) == 12500000
    text = json.dumps(payload)
    assert "chunk-1" in text and "watcher" in text
    assert "material-sentinel" not in text
    assert "reasoning-sentinel" not in text
    assert "quote-sentinel" not in text
    root = payload_for({**RECORD, "event": "tool_loop_finished", "stop_reason": "completed"})
    root_span = root["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert root_span["spanId"] == root_span_id("run-1")
    assert "parentSpanId" not in root_span


def test_missing_duration_is_explicit_and_archived_import_is_labeled():
    from anlan.infrastructure.telemetry import payload_for, trace_id

    record = {k: v for k, v in RECORD.items() if k != "elapsed_ms"}
    span = payload_for(record, archived=True)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["startTimeUnixNano"] == span["endTimeUnixNano"]
    attributes = {a["key"]: a["value"] for a in span["attributes"]}
    assert attributes["anlan.duration_recorded"] == {"boolValue": False}
    assert attributes["anlan.recording_mode"] == {"stringValue": "archived_import"}
    assert span["traceId"] != trace_id("run-1")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://remote.example/v1/traces",
        "http://127.0.0.1@remote.example/v1/traces",
        "http://user:password@127.0.0.1:4318/v1/traces",
        "http://127.0.0.1:4318/wrong",
        "http://127.0.0.1:4318/v1/traces?secret=1",
    ],
)
def test_export_destination_is_local_and_credential_free(endpoint):
    from anlan.infrastructure.telemetry import LocalOtlpExporter

    with pytest.raises(ValueError):
        LocalOtlpExporter(endpoint)


@pytest.mark.parametrize(
    "failure",
    [
        "status",
        "redirect",
        "partial",
        "timeout",
        "oversized",
        "deep_json",
    ],
)
def test_export_failure_does_not_retry_or_leak_remote_response(failure):
    from anlan.infrastructure.telemetry import LocalOtlpExporter

    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "127.0.0.1"
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-sentinel")
        if failure == "redirect":
            return httpx.Response(307, headers={"location": "https://remote.example"})
        if failure == "partial":
            return httpx.Response(200, json={"partialSuccess": {"rejectedSpans": "1"}})
        if failure == "oversized":
            return httpx.Response(200, content=b" " * 4097)
        if failure == "deep_json":
            return httpx.Response(200, content=b"[" * 2000 + b"0" + b"]" * 2000)
        return httpx.Response(500, text="secret-sentinel")

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        exporter = LocalOtlpExporter("http://127.0.0.1:4318/v1/traces", client=client)
        assert exporter.export(RECORD) is False
    assert len(calls) == 1


async def test_remote_export_failure_keeps_local_json_and_workflow_result(tmp_path):
    from anlan.infrastructure.telemetry import LocalOtlpExporter

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        trace = JsonlTrace(
            tmp_path / "trace.jsonl",
            exporter=LocalOtlpExporter("http://127.0.0.1:4318/v1/traces", client=client),
        )
        service = WorkflowService(OfflineAnalyzer(), trace)
        state = await service.start(Identity(tenant_id="synthetic", user_id="owner"), DEMO_FIELDS)
    assert state["status"] == "waiting_input"
    assert state["trace_warning"] == "trace_export_failed"
    assert len(trace.path.read_text(encoding="utf-8").splitlines()) == 1


async def test_exporter_lifecycle_exception_does_not_interrupt_business(tmp_path):
    from anlan.infrastructure.telemetry import LocalOtlpExporter

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client.close()
    trace = JsonlTrace(
        tmp_path / "trace.jsonl",
        exporter=LocalOtlpExporter("http://127.0.0.1:4318/v1/traces", client=client),
    )
    service = WorkflowService(OfflineAnalyzer(), trace)
    state = await service.start(Identity(tenant_id="synthetic", user_id="owner"), DEMO_FIELDS)
    assert state["status"] == "waiting_input"
    assert state["trace_warning"] == "trace_export_failed"
    assert len(trace.path.read_text(encoding="utf-8").splitlines()) == 1


def test_successful_export_with_http_double():
    from anlan.infrastructure.telemetry import LocalOtlpExporter

    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as client:
        assert LocalOtlpExporter("http://127.0.0.1:4318/v1/traces", client=client).export(RECORD)


def test_malformed_archived_usage_is_rejected_without_losing_business_control():
    from anlan.infrastructure.telemetry import LocalOtlpExporter

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: pytest.fail("malformed telemetry must not be transmitted")
        )
    ) as client:
        exporter = LocalOtlpExporter("http://127.0.0.1:4318/v1/traces", client=client)
        assert exporter.export({**RECORD, "usage": "invalid metadata"}, archived=True) is False
