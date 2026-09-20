"""只读旧JSONL并导入独立archived trace；不执行工具、模型或状态变更。"""

import argparse
import hashlib
import json
import os
from pathlib import Path

from anlan.telemetry import LocalOtlpExporter, trace_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("ANLAN_OTLP_ENDPOINT"):
        parser.error("先加载本地Jaeger环境。")
    exporter = LocalOtlpExporter(os.environ["ANLAN_OTLP_ENDPOINT"])
    raw = args.source.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    report = {
        "mode": "archived_import",
        "requests_this_run": 0,
        "source": str(args.source),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "events": len(records),
        "exported": 0,
        "failed": 0,
        "trace_ids": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        identifiers = set()
        processed = 0
        try:
            for record in records:
                valid_id = (
                    isinstance(record, dict)
                    and isinstance(record.get("run_id"), str)
                    and bool(record["run_id"].strip())
                )
                if valid_id:
                    identifiers.add(trace_id(record["run_id"], archived=True))
                try:
                    ok = valid_id and exporter.export(record, archived=True)
                except Exception:
                    ok = False
                report["exported" if ok else "failed"] += 1
                processed += 1
        finally:
            report["trace_ids"] = sorted(identifiers)
            report["unprocessed"] = len(records) - processed
            report["status"] = (
                "passed"
                if report["failed"] == 0 and not report["unprocessed"]
                else "partial_failure"
            )
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
