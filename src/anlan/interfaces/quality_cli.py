"""Explicit offline evidence modes; live reruns remain in the budgeted experiment runner."""

import argparse
import hashlib
import json
from pathlib import Path

from anlan.workflows.quality import inspect_records, load_corpus, read_bounded, replay_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["inspect", "replay"])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--split", choices=["dev", "holdout"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.mode == "replay" and not args.split:
        parser.error("Replay requires an explicit split")
    # Exclusive creation precedes work; failed runs cannot overwrite earlier evidence.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = args.output.open("x", encoding="utf-8")
    except FileExistsError:
        parser.error("Use a new report path")
    report = {"status": "failed", "mode": args.mode, "model_requests": 0}
    with stream:
        try:
            records = load_corpus(args.manifest, args.root)
            report["manifest_sha256"] = hashlib.sha256(read_bounded(args.manifest)).hexdigest()
            report["rows"] = (inspect_records(records) if args.mode == "inspect" else
                              replay_records(records, split=args.split))
            report["status"] = "completed"
            if args.mode == "replay":
                report["matches_expected"] = sum(r["matches_expected"] for r in report["rows"])
                report["not_replayable"] = sum(r["actual"] == "not_replayable"
                                               for r in report["rows"])
        except (ValueError, OSError, KeyError, TypeError, IndexError,
                AttributeError, RecursionError) as exc:
            report["error_category"] = type(exc).__name__
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
