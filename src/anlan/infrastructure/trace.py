"""Small local trace sink; no raw material, credential, response body or hidden reasoning."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anlan.infrastructure.telemetry import LocalOtlpExporter


class JsonlTrace:
    def __init__(self, path: Path | None = None, *, exporter=None):
        self.path = path
        self.exporter = exporter
        self.warning = None
        self.invalid_export = False
        if exporter is None and os.environ.get("ANLAN_OTLP_ENDPOINT"):
            try:
                self.exporter = LocalOtlpExporter(os.environ["ANLAN_OTLP_ENDPOINT"])
            except ValueError:
                self.invalid_export = True

    def emit(self, event: str, state: dict[str, Any], **details: Any) -> bool:
        self.warning = None
        if self.path is None and self.exporter is None and not self.invalid_export:
            return True
        record = {
            "event": event, "timestamp": datetime.now(UTC).isoformat(),
            "data_origin": "SYNTHETIC", "schema_version": "trace-v1",
            **{key: state[key] for key in (
                "task_id", "run_id", "correlation_id", "revision", "status")},
            **details,
        }
        try:
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            self.warning = "trace_write_failed"
            return False  # Caller must surface the gap; logging is not a business gate.
        try:
            exported = self.exporter is None or self.exporter.export(record)
        except Exception:
            exported = False
        if self.invalid_export or not exported:
            self.warning = "trace_export_failed"
            return False
        return True
