"""The same local/CI checks; skipped PG tests or missing output cannot pass."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url
from anlan.infrastructure.events import EventStore
from anlan.infrastructure.perception import PerceptionStore
from anlan.infrastructure.postgres import initialize_database

ROOT = Path(__file__).resolve().parents[1]


def source_fingerprints(root=ROOT):
    paths = [root / "pyproject.toml", root / "uv.lock"]
    for directory in ("src", "tests", "scripts", "evals", "examples"):
        paths.extend(
            p
            for p in (root / directory).rglob("*")
            if p.is_file() and p.suffix in {".py", ".json", ".sql", ".md"}
        )
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(set(paths))
        if p.is_file()
    }


def verify_sources(before, root=ROOT):
    after = source_fingerprints(root)
    if before != after:
        raise ValueError("CI source changed during verification; results cannot pass")
    return after


async def initialize():
    dsn = database_url()
    await initialize_database(dsn)
    await EventStore(dsn).initialize()
    await PerceptionStore(dsn).initialize()
    await BudgetLedger(dsn).initialize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new evidence path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "failed", "checks": [], "requests_this_run": 0}

    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    try:
        report["sources_before"] = source_fingerprints()
        if not os.environ.get("ANLAN_TEST_DATABASE_URL"):
            raise ValueError("Explicit real PG test DSN required")
        asyncio.run(initialize(), loop_factory=asyncio.SelectorEventLoop)
        checks = [
            ("lock", ["uv", "lock", "--check"]),
            ("lint", [sys.executable, "-m", "ruff", "check", "src", "tests", "evals", "scripts"]),
            (
                "tests",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--junitxml=" + str(args.output.with_suffix(".xml")),
                ],
            ),
        ]
        for name, command in checks:
            log = args.output.with_suffix("." + name + ".log")
            with log.open("xb") as output:
                run = subprocess.run(
                    command,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    env=os.environ | {"PYTHONIOENCODING": "utf-8"},
                    timeout=900,
                )
            report["checks"].append({"name": name, "returncode": run.returncode})
            report["sources_after"] = source_fingerprints()
            save()
            verify_sources(report["sources_before"])
            if run.returncode:
                raise ValueError("Check failed; log retained")
        suite = ET.parse(args.output.with_suffix(".xml")).getroot().find("testsuite")
        report["test_summary"] = {
            k: int(suite.attrib[k]) for k in ("tests", "errors", "failures", "skipped")
        }
        if report["test_summary"]["tests"] == 0 or any(
            report["test_summary"][k] for k in ("errors", "failures", "skipped")
        ):
            raise ValueError("Empty or incomplete tests cannot pass")
        report["status"] = "passed"
    except Exception as exc:
        report["error_category"] = type(exc).__name__
    finally:
        save()
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "checks", "test_summary", "error_category")
                if k in report
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
