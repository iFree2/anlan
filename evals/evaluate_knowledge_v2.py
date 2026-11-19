"""Offline native knowledge evaluation. 0=pass, 2=pending/blocked, 1=invalid."""

import argparse
import asyncio
import json
from pathlib import Path

from anlan.evaluation.knowledge_runner import run_knowledge_suite


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        index = asyncio.run(run_knowledge_suite(args.catalog, args.artifacts_dir))
        path = Path(index["artifact_dir"]) / "report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(dict(output=str(path), gate=report["gate"], cases=len(index["cases"]))))
        return 0 if report["gate"] == "pass" else 2
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(json.dumps(dict(error=type(exc).__name__)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
