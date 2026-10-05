"""Read-only final evidence audit; emits a new bounded engineering gate report."""

import asyncio
import hashlib
import importlib.util
import json
import re
from pathlib import Path

from anlan.infrastructure.budget import BudgetLedger
from anlan.infrastructure.db import database_url

ROOT = Path(__file__).resolve().parents[5]
PHASE = ROOT / "docs/phases/phase-07-takeover-career"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def same_files(hashes, root=ROOT):
    return all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h
               for p, h in hashes.items())


def main():
    target = Path(__file__).with_name("gate-final.json")
    with target.open("x", encoding="utf-8") as output:
        report = {"status": "failed", "checks": {}, "personal_takeover": "not_verified",
                  "open_quality_items": ["Q-P6-001", "Q-P6-002"], "model_generalization": "not_verified",
                  "mem0_runtime": "not_executed", "new_model_requests_this_gate": 0}
        try:
            ci = read(PHASE / "evidence/wp04/ci-final.json")
            spec = importlib.util.spec_from_file_location("ci_gate_source", ROOT / "scripts/ci.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            report["checks"]["final_ci"] = (
                ci["status"] == "passed" and ci["test_summary"] == {
                    "tests": 456, "errors": 0, "failures": 0, "skipped": 0}
                and ci["sources_before"] == ci["sources_after"] == module.source_fingerprints())
            demo_dir = PHASE / "evidence/wp01/demo-v2"
            demo = read(demo_dir / "report.json")
            report["checks"]["takeover_demo"] = (
                demo["status"] == "passed" and len(demo["steps"]) == 5
                and all(s["status"] == "passed" for s in demo["steps"])
                and demo["model_request_delta"] == 0 and same_files(demo["source_after"])
                and same_files(demo["artifacts"], demo_dir))
            fault = read(PHASE / "evidence/wp01/fault-checks-v1.json")
            report["checks"]["failure_preservation"] = (
                fault["repeat_exit"] == 2 and fault["unavailable_exit"] == 1
                and all(fault[k] for k in ("original_sha_equal", "budget_before_unknown",
                                          "budget_after_unknown", "delta_unknown",
                                          "steps_not_started", "secret_absent")))
            reuse = read(PHASE / "evidence/wp02/reuse-v1/report.json")
            report["checks"]["bounded_reuse"] = (
                reuse["status"] == "passed" and reuse["model_request_delta"] == 0
                and reuse["transfer"]["unknown_observation_ids"] == ["o1"]
                and reuse["transfer"]["business_rules_reused"] is False
                and len(reuse["memory_history"]) == 7
                and same_files(reuse["fixture_sha256"], ROOT / "examples/synthetic/confined-space-v1"))
            live = read(PHASE / "evidence/wp03/live-v1.json")
            manifest = ROOT / "examples/synthetic/multimodal-v1/manifest.json"
            data = read(manifest)
            report["checks"]["finite_multimodal"] = (
                live["status"] == "completed" and len(live["rows"]) == 4
                and len(live["owned_attempts"]) == 4
                and live["budget_after"]["total_reserved"] == 46
                and hashlib.sha256(manifest.read_bytes()).hexdigest() == live["manifest_sha256"]
                and all(hashlib.sha256((manifest.parent / c["image"]).read_bytes()).hexdigest()
                        == c["image_sha256"] for c in data["cases"])
                and hashlib.sha256((ROOT / "evals/evaluate_multimodal.py").read_bytes()).hexdigest()
                == live["runner_sha256"])
            installed = read(ROOT / "docs/phases/phase-06-quality-reliability/evidence/wp04/"
                             "clean-service.json")["interpreter"]["package_files"]
            report["checks"]["p6_package_sources_unchanged"] = (
                len(installed) == 88 and same_files(installed))
            budget = asyncio.run(BudgetLedger(database_url()).snapshot(),
                                 loop_factory=asyncio.SelectorEventLoop)
            report["budget_final"] = budget
            report["checks"]["budget_unchanged_after_wp03"] = budget == live["budget_after"]
            user = read(ROOT / ".runtime/p7-wp01/user-before.json")
            user.pop("docs/learning-log.md")
            current = (ROOT / "docs/learning-log.md").read_bytes()
            nl = b"\r\n" if b"\r\n" in current else b"\n"
            prefix = current.split(nl + nl + b'<a id="p7"></a>', 1)[0]
            prefix = re.sub(rb'- \[P7.*?\r?\n\r?\n(?=<a id="learning-notes")',
                            b"", prefix, count=1, flags=re.DOTALL)
            report["checks"]["user_preserved"] = (
                same_files(user) and prefix == (ROOT / ".runtime/p7-wp01/learning-before.md").read_bytes())
            links = []
            for path in PHASE.glob("*.md"):
                for ref in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding="utf-8")):
                    if not ref.startswith(("http", "#")):
                        links.append((path.parent / ref.split("#")[0]).exists())
            report["checks"]["handover_links"] = bool(links) and all(links)
            report["evidence_sha256"] = {
                p.relative_to(PHASE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((PHASE / "evidence").rglob("*"))
                if p.is_file() and p not in (target, Path(__file__).resolve())}
            report["generator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            if all(report["checks"].values()):
                report["status"] = "passed"
        except Exception as exc:
            report["error_category"] = type(exc).__name__
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({k: report.get(k) for k in ("status", "checks", "error_category")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
