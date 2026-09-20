import importlib.util
import json
import sys
from pathlib import Path


def test_import_keeps_partial_delivery_report_for_invalid_record(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "trace_import_test", Path("scripts/import_trace.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Exporter:
        def export(self, record, archived=False):
            assert archived
            return record.get("run_id") == "run-1"

    monkeypatch.setattr(module, "LocalOtlpExporter", lambda endpoint: Exporter())
    monkeypatch.setenv("ANLAN_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    source = tmp_path / "source.jsonl"
    source.write_text('{"run_id":"run-1"}\n{}\n', encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv", ["import_trace", "--source", str(source), "--output", str(output)]
    )
    assert module.main() == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "partial_failure"
    assert (report["exported"], report["failed"]) == (1, 1)
    assert len(report["trace_ids"]) == 1
