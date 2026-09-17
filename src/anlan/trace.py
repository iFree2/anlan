"""Small local trace sink; no raw material, credential, response body or hidden reasoning."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonlTrace:
    def __init__(self, path: Path | None = None):
        self.path = path

    def emit(self, event: str, state: dict[str, Any], **details: Any) -> bool:
        if self.path is None:
            return True
        record = {
            "event": event, "timestamp": datetime.now(UTC).isoformat(),
            "data_origin": "SYNTHETIC", "schema_version": "trace-v1",
            **{key: state[key] for key in (
                "task_id", "run_id", "correlation_id", "revision", "status")},
            **details,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return False  # Caller must surface the gap; logging is not a business gate.
        return True
