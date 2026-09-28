"""Run from repository root after evidence exists; never executes models or overwrites reports."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PHASE = HERE.parent.parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    paths = {
        "ci": HERE / "ci-final.json", "service": HERE / "clean-service.json",
        "legacy": HERE / "legacy-gate.json", "sql": HERE / "sql-analysis.json",
        "benchmark": HERE / "benchmark-v1.json", "wheel": HERE / "wheel.json",
        "perception": PHASE / "evidence/wp01/live-v1.json",
        "replay": PHASE / "evidence/wp02/dev-after.json",
        "holdout": PHASE / "evidence/wp02/holdout-once.json",
        "judge": PHASE / "evidence/wp03/live-v2.json",
        "old_perception": ROOT / "docs/phases/phase-05-events-service/evidence/wp02/live-v1.json",
    }
    d = {name: read(path) for name, path in paths.items()}
    spec = importlib.util.spec_from_file_location("ci", ROOT / "scripts/ci.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ci = d["ci"]
    current = module.source_fingerprints(ROOT)
    installed = d["service"]["interpreter"]["package_files"]
    source_package = {p: h for p, h in current.items() if p.startswith("src/anlan/")}
    b, j = d["benchmark"], d["judge"]
    checks = {
        "full_ci_current_source_zero_skips": ci["status"] == "passed"
            and ci["test_summary"] == {"tests": 434, "errors": 0, "failures": 0, "skipped": 0}
            and ci["sources_before"] == ci["sources_after"] == current,
        "current_clean_wheel_two_chains_restart": d["service"]["status"] == "passed"
            and d["service"]["owned_process_stopped"] and d["service"]["restarts"] == 1
            and len(d["service"]["rows"]) == 2 and installed == source_package
            and d["wheel"]["status"] == "completed",
        "p5_and_p4_frozen_engineering_regressions": d["legacy"]["status"] == "passed"
            and len(d["legacy"]["checks"]) == 8
            and all(c["passed"] for c in d["legacy"]["checks"]),
        "bounded_live_perception_minimum": d["perception"]["application_accepted"] == 2
            and d["perception"]["requests_this_run"] == 2
            and d["old_perception"]["application_accepted"] == 0
            and d["old_perception"]["requests_this_run"] == 2,
        "replay_and_contract_holdout_separated": d["replay"]["matches_expected"] == 6
            and d["replay"]["not_replayable"] == 2
            and d["holdout"]["matches_expected"] == 5
            and len(d["replay"]["rows"]) == 6 and len(d["holdout"]["rows"]) == 5,
        "finite_judge_single_dual_and_no_gain_retained": j["status"] == "completed"
            and j["requests_this_run"] == 8 and j["request_accounting_complete"]
            and len(j["judge"]) == 2 and len(j["results"]) == 2
            and sum(r["scores"]["correct"] for r in j["judge"]) == 5
            and all(r["same_risk_context"] and r["ablation"]["model_requests"] == 0
                    for r in j["results"]),
        "readonly_sql_includes_old_failures": d["sql"]["status"] == "passed"
            and d["sql"]["read_only"]["transaction_read_only"] == "on"
            and sum(r["reviews"] for r in d["sql"]["rows"]) == 4,
        "performance_failure_honestly_preserved": b["status"] == "failed"
            and b["owned_process_stopped"]
            and [g["failed"] for g in b["groups"]] == [0, 11, 13]
            and all(len(g["samples"]) == 24 for g in b["groups"])
            and all(s["status_code"] == 409 for g in b["groups"]
                    for s in g["samples"] if not s["passed"]),
        "wp04_no_model_spend": all(d[k]["budget_before"] == d[k]["budget_after"]
                                    for k in ("legacy", "sql", "benchmark", "service"))
            and d["legacy"]["budget_after"]["total_reserved"] == 42,
    }
    report = {
        "status": "passed" if all(checks.values()) else "failed", "checks": checks,
        "scope": "engineering_and_reproducible_quality_evidence_not_production_capability",
        "installed_files": len(installed), "performance_status": "not_passed",
        "judge_autonomous_quality_gate": "not_validated", "open_quality_items": ["Q-P6-001", "Q-P6-002"],
        "legacy_gate_model_quality_fields": "historical_P5_labels_not_current_quality_registry",
        "personal_mastery": "not_verified", "compose": "not_run", "remote_ci": "not_run",
        "evidence_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for name, path in paths.items()},
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with (HERE / "gate-final.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
