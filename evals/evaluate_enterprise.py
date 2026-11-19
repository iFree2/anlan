"""Offline reporting only. Exit 0=pass, 2=pending/blocked, 1=invalid input/output."""

import argparse
import asyncio
import json
from pathlib import Path

from anlan.evaluation import adapt_materials_v1, evaluate_bundle, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle", type=Path)
    source.add_argument("--legacy-materials", type=Path)
    source.add_argument("--run-scenarios", type=Path)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.run_scenarios:
            if not args.artifacts_dir or args.output or args.manifest:
                raise ValueError("runner requires --artifacts-dir; no --output or --manifest")
            from anlan.evaluation.runner import run_suite

            index = asyncio.run(run_suite(args.run_scenarios, args.artifacts_dir))
            report_path = Path(index["artifact_dir"]) / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print(
                json.dumps(
                    {
                        "gate": report["gate"],
                        "output": str(report_path),
                        "cases": len(index["cases"]),
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if report["gate"] == "pass" else 2
        if not args.output or args.artifacts_dir:
            raise ValueError("legacy/bundle modes require --output and no --artifacts-dir")
        if args.legacy_materials:
            if not args.manifest:
                raise ValueError("--manifest is required for legacy adaptation")
            payload = adapt_materials_v1(
                json.loads(args.legacy_materials.read_text(encoding="utf-8-sig")),
                json.loads(args.manifest.read_text(encoding="utf-8-sig")),
            )
        else:
            if args.manifest:
                raise ValueError("--manifest only applies to legacy adaptation")
            payload = json.loads(args.bundle.read_text(encoding="utf-8-sig"))
        report = evaluate_bundle(payload)
        write_report(args.output, report)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "output": str(args.output),
                "cases": report["coverage"]["observed_cases"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["gate"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
