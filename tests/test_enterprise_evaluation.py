import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


def api():
    try:
        return importlib.import_module("anlan.evaluation")
    except ModuleNotFoundError:
        pytest.fail("E1 unified offline evaluation contract is not implemented")


def manifest():
    return {
        "schema_version": "enterprise-eval-v2",
        "code_version": "b8b80d4+E1-working-tree",
        "prompt_version": "not_applicable:offline",
        "model_version": "not_applicable:offline",
        "knowledge_version": "not_applicable:contract-only",
        "dataset_version": "synthetic-seen-contract-v1",
        "scorer_version": "enterprise-scorer-v2.0",
        "environment": "pytest-local",
        "run_at": "2026-11-16T10:00:00+08:00",
        "fixed_at": "2026-11-16T09:00:00+08:00",
        "request_limit": 0,
        "request_attempts": 0,
        "required_case_ids": ["contract-1"],
    }


def check(status="pass"):
    return {"status": status, "evidence": "synthetic contract assertion"}


def case():
    return {
        "case_id": "contract-1",
        "origin": "SYNTHETIC",
        "split": "seen_regression",
        "slice": "contract",
        "severity": "critical",
        "structure": check(),
        "semantic": check(),
        "semantic_source": "deterministic",
        "human": check("pending"),
        "human_reviewer": None,
        "safety": {key: check() for key in api().SAFETY_CHECKS},
        "errors": [],
        "latency_ms": None,
        "cost_usd": None,
        "total_tokens": None,
    }


def report(rows=None, meta=None):
    return api().evaluate_bundle(
        {"manifest": meta or manifest(), "cases": [case()] if rows is None else rows}
    )


def test_separates_structure_semantic_and_pending_human_without_fake_measurements():
    result = report()
    assert result["gate"] == "pending"
    assert result["quality"]["structure"]["pass"] == 1
    assert result["quality"]["human"]["pending"] == 1
    assert result["reliability"]["latency_ms_p50"] is None
    assert result["cost"]["total_cost_usd"] is None
    assert result["cost"]["total_tokens"] is None


@pytest.mark.parametrize("field", list(manifest()))
def test_manifest_requires_every_version_and_run_field(field):
    meta = manifest()
    del meta[field]
    with pytest.raises(ValidationError):
        report(meta=meta)


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": 1},
        {"schema_version": "v1"},
        {"scorer_version": "unknown"},
        {"code_version": " "},
        {"required_case_ids": []},
        {"required_case_ids": ["contract-1", "contract-1"]},
        {"run_at": "2026-11-16T10:00:00"},
        {"request_attempts": 1},
        {"request_attempts": True},
    ],
)
def test_manifest_rejects_invalid_or_unversioned_contract(change):
    with pytest.raises(ValidationError):
        report(meta=manifest() | change)


def test_empty_missing_and_missing_checks_never_pass():
    assert report([])["gate"] == "pending"
    assert report([])["coverage"]["missing_case_ids"] == ["contract-1"]
    row = case()
    row["safety"] = {}
    result = report([row])
    assert result["gate"] == "pending"
    assert len(result["safety"]["unmeasured"]) == len(api().SAFETY_CHECKS)
    row["semantic"] = check("pending")
    assert report([row])["quality"]["semantic"]["pending"] == 1


def test_duplicate_and_unexpected_case_ids_rejected():
    row = case()
    with pytest.raises(ValidationError, match="duplicate"):
        report([row, row])
    with pytest.raises(ValidationError, match="unexpected"):
        report([row | {"case_id": "unknown"}])


def test_each_safety_failure_blocks_independently_even_with_pending_or_high_quality():
    for key in api().SAFETY_CHECKS:
        row = case()
        row["safety"][key] = check("fail")
        result = report([row])
        assert result["gate"] == "blocked"
        assert result["safety"]["blockers"] == [
            {"case_id": "contract-1", "check": key, "evidence": check()["evidence"]}
        ]
        assert result["quality"]["structure"]["pass"] == 1


def test_all_measured_pass_requires_attributed_human_review():
    row = case()
    row["human"] = check()
    with pytest.raises(ValidationError, match="reviewer"):
        report([row])
    row["human_reviewer"] = "test-fixture-only-reviewer"
    assert report([row])["gate"] == "pass"
    row["errors"] = ["tool timeout"]
    assert report([row])["gate"] == "blocked"


@pytest.mark.parametrize(
    "change",
    [
        {"latency_ms": -1},
        {"cost_usd": float("nan")},
        {"total_tokens": True},
        {"split": "unseen_holdout"},
        {"safety": {"judge_safety": check()}},
        {"structure": {"status": "pass", "evidence": ""}},
    ],
)
def test_case_rejects_invalid_measurement_or_invented_safety(change):
    with pytest.raises(ValidationError):
        report([case() | change])


def test_partial_measurements_not_presented_as_complete():
    row = case()
    other = copy.deepcopy(row) | {
        "case_id": "contract-2",
        "latency_ms": 12.0,
        "cost_usd": 0.02,
        "total_tokens": 20,
    }
    result = report([row, other], manifest() | {"required_case_ids": ["contract-1", "contract-2"]})
    assert result["reliability"]["latency_measured_cases"] == 1
    assert result["reliability"]["latency_ms_p50"] is None
    assert result["cost"]["total_cost_usd"] is None
    assert result["cost"]["known_cost_usd"] == 0.02


def test_legacy_materials_adapter_keeps_history_and_unknowns(tmp_path):
    source = Path("docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json")
    before = source.read_bytes()
    converted = api().adapt_materials_v1(
        json.loads(before),
        manifest() | {"required_case_ids": [f"anlan2-dev-{i:03}" for i in range(1, 4)]},
    )
    result = api().evaluate_bundle(converted)
    assert source.read_bytes() == before
    assert result["gate"] == "blocked"  # Historical third case has exact_match=false.
    assert result["quality"]["semantic"]["pending"] == 3
    assert result["quality"]["human"]["pending"] == 3
    assert result["cost"]["total_cost_usd"] is None
    assert result["provenance"]["adapter"] == "materials-v1"
    destination = tmp_path / "report.json"
    api().write_report(destination, result)
    with pytest.raises(FileExistsError):
        api().write_report(destination, result)
    assert source.read_bytes() == before


def test_offline_cli_reports_pending_and_refuses_overwrite(tmp_path):
    source = tmp_path / "bundle.json"
    source.write_text(json.dumps({"manifest": manifest(), "cases": [case()]}), encoding="utf-8")
    output = tmp_path / "report.json"
    command = [
        sys.executable,
        "evals/evaluate_enterprise.py",
        "--bundle",
        str(source),
        "--output",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["gate"] == "pending"
    before = output.read_bytes()
    again = subprocess.run(command, capture_output=True, text=True)
    assert again.returncode == 1
    assert output.read_bytes() == before


def test_legacy_adapter_rejects_online_source_in_offline_only_entry():
    source = json.loads(
        Path("docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json").read_text(
            encoding="utf-8"
        )
    )
    source["mode"] = "deepseek"
    with pytest.raises(ValueError, match="offline"):
        api().adapt_materials_v1(
            source, manifest() | {"required_case_ids": [f"anlan2-dev-{i:03}" for i in range(1, 4)]}
        )


def test_judge_cannot_fill_safety_contract_or_authorize_without_human():
    row = case() | {"semantic_source": "judge"}
    assert report([row])["gate"] == "pending"
    row["safety"]["unauthorized_access"]["source"] = "judge"
    with pytest.raises(ValidationError):
        report([row])


def test_completed_measurements_and_failed_dimensions_are_reported_separately():
    row = case() | {"latency_ms": 8.0, "cost_usd": 0.0, "total_tokens": 0}
    row["semantic"] = check("fail")
    result = report([row])
    assert result["gate"] == "blocked"
    assert result["safety"]["blockers"] == []
    assert result["reliability"]["latency_ms_p50"] == 8.0
    assert result["cost"]["total_tokens"] == 0
    assert result["cost"]["total_cost_usd"] == 0.0


def test_unknown_historical_fixed_time_is_explicit_null():
    row = case() | {"human": check(), "human_reviewer": "fixture-only"}
    result = report([row], manifest() | {"fixed_at": None})
    assert result["manifest"]["fixed_at"] is None
    assert result["gate"] == "pending"


def test_legacy_false_issue_set_match_does_not_claim_structural_invalidity():
    source = json.loads(
        Path("docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = api().adapt_materials_v1(
        source, manifest() | {"required_case_ids": [f"anlan2-dev-{i:03}" for i in range(1, 4)]}
    )
    third = bundle["cases"][2]
    assert third["structure"]["status"] == "pending"
    assert third["legacy_issue_set"]["status"] == "fail"
    result = api().evaluate_bundle(bundle)
    assert result["quality"]["structure"]["pending"] == 3
    assert result["legacy_metrics"]["issue_set"] == {"pass": 2, "fail": 1, "pending": 0}


def test_missing_required_case_keeps_complete_metrics_unknown():
    row = case() | {"latency_ms": 12.0, "cost_usd": 0.02, "total_tokens": 20}
    result = report([row], manifest() | {"required_case_ids": ["contract-1", "missing-2"]})
    assert result["gate"] == "pending"
    assert result["reliability"]["latency_ms_p50"] is None
    assert result["reliability"]["latency_ms_p95"] is None
    assert result["cost"]["total_cost_usd"] is None
    assert result["cost"]["total_tokens"] is None
    assert result["cost"]["known_tokens"] == 20
    assert result["cost"]["known_cost_usd"] == 0.02
