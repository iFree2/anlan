"""Offline context ablation: same synthetic input, exact bytes, no model/token claims."""

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

from anlan.context import build_context
from anlan.contracts import Identity


def evaluate(path):
    raw = path.read_bytes()
    fixture = json.loads(raw)
    identity = Identity.model_validate(fixture["identity"])
    now = datetime.fromisoformat(fixture["as_of"])
    results = []
    for case in fixture["cases"]:
        memory = {**fixture["memory"], **case.get("memory_patch", {})}
        options = case.get("options", {})
        context = build_context(identity, fixture["snapshot"], fixture["observations"], [memory],
                                now=now, **options)
        data = json.loads(context["messages"][1]["content"])
        actual = {"memory_selected": bool(data["preferences"]),
                  "unknown_preserved": data["observations"][0]["reason"] == "expired",
                  "knowledge_selected": bool(data["knowledge"])}
        results.append({"case_id": case["case_id"], "expected": case["expected"],
                        "actual": actual, "passed": actual == case["expected"],
                        "context": copy.deepcopy(context)})
    return {"data_origin": "SYNTHETIC", "mode": "offline_context_only",
            "exposure": "developer_seen", "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "requests_this_run": 0, "usage": None, "results": results,
            "status": "passed" if all(r["passed"] for r in results) else "failed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate(Path(__file__).parent / "context-v1/cases.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
