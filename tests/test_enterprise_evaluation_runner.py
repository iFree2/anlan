"""E2a actual offline calls, observations and causal scores, no provider/PG."""

import copy
import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path("evals/enterprise-eval-v2/runner-v1")


def api():
    try:
        return importlib.import_module("anlan.evaluation.runner")
    except ModuleNotFoundError:
        pytest.fail("E2a native offline runner is not implemented")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def execute(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline suite attempted external connection")

    monkeypatch.setenv("ANLAN_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    return await api().run_suite(ROOT / "cases.json", tmp_path / "runs")


def observation(index, suffix):
    entry = next(r for r in index["cases"] if r["case_id"].endswith(suffix))
    return read(Path(index["artifact_dir"]) / entry["observation"]["path"])


def test_catalog_rejects_duplicate_and_precomputed_scores_and_external_root(tmp_path):
    module = api()
    catalog = read(ROOT / "cases.json")
    duplicate = copy.deepcopy(catalog)
    duplicate["cases"].append(duplicate["cases"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        module.Catalog.model_validate(duplicate)
    catalog["cases"][0]["safety"] = {"unauthorized_access": "pass"}
    with pytest.raises(ValidationError):
        module.Catalog.model_validate(catalog)
    outside = tmp_path / "cases.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="trusted fixture root"):
        module.load_catalog(outside)
    with pytest.raises(ValueError):
        module.fixture_path("../manifest.json")


async def test_normal_calls_native_loop_and_preserves_state(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    row = observation(executed, "fact-normal")
    assert row["native"]["stop_reason"] == "completed"
    assert row["counts"] == {"model": 2, "handler": 2, "reader": 4}
    assert row["diagnostics"]["state_unchanged"] is True
    assert row["diagnostics"]["binding_consistent"] is True
    assert row["loop_run_id"] == row["native"]["run_id"]
    report = read(Path(executed["artifact_dir"]) / "report.json")
    result = next(r for r in report["cases"] if r["case_id"] == row["case_id"])
    assert result["safety"]["stale_revision"]["status"] == "pending"
    assert result["human"]["status"] == result["semantic"]["status"] == "pending"


async def test_outside_ref_and_cross_tenant_never_invoke_handler(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    outside = observation(executed, "outside-ref")
    assert outside["native"]["results"][0]["reason"] == "outside_references"
    assert outside["counts"]["handler"] == outside["counts"]["reader"] == 0
    denied = observation(executed, "cross-tenant")
    assert denied["exception"] == "AccessDenied"
    assert denied["loop_run_id"] is None
    assert denied["counts"] == {"model": 0, "handler": 0, "reader": 0}
    assert denied["native"] is None
    assert denied["diagnostics"]["state_unchanged"] is True


async def test_reader_fault_and_bad_citation_are_real_observations(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    fault = observation(executed, "tool-error")
    assert any(r["reason"] == "data_error" for r in fault["native"]["results"])
    assert fault["counts"]["reader"] > 0
    bad = observation(executed, "bad-citation")
    assert bad["native"]["tool_calls"] == 2
    assert bad["native"]["stop_reason"] == "unsupported_citation"
    assert bad["native"]["summary"] is None
    assert bad["native"]["summary_status"] == "not_available"


async def test_native_governance_current_withdrawal_and_missing_authority(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    for suffix, allowed, reason in [
        ("knowledge-current", True, "allowed"),
        ("knowledge-withdrawn", False, "withdrawn"),
        ("knowledge-missing-authority", False, "missing_authority"),
    ]:
        row = observation(executed, suffix)
        assert row["native"] == {"allowed": allowed, "reason": reason}
        assert row["diagnostics"]["input_unchanged"] is True
        assert row["counts"] == {"model": 0, "handler": 0, "reader": 0}
    withdrawn = observation(executed, "knowledge-withdrawn")
    assert withdrawn["inputs"]["authority"]["withdrawal"]["revision"] == 3
    assert withdrawn["inputs"]["manifest"]["generation"] == 1


async def test_scoring_uses_observation_not_expected_scores(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    module = importlib.import_module("anlan.evaluation.scoring")
    index = executed
    row = observation(index, "outside-ref")
    spec = next(
        s for s in api().load_catalog(ROOT / "cases.json").cases if s.case_id == row["case_id"]
    )
    assert module.score_observation(spec, row)["safety"]["unauthorized_access"]["status"] == "pass"
    row["native"]["results"][0]["executed"] = True
    result = module.score_observation(spec, row)
    assert result["safety"]["unauthorized_access"]["status"] == "fail"
    assert result["structure"]["status"] == "pass"  # Valid shape, wrong behavior.
    assert result["safety"]["alarm_mutation"]["status"] == "pending"


async def test_strict_manifest_sidecar_binding_and_missing_trace(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    module = api()
    root = Path(executed["artifact_dir"])
    assert module.verify_run(root / "run-index.json")["valid"] is True
    assert len(executed["cases"]) == 8
    manifest = read(root / "manifest.json")
    from anlan.evaluation import Manifest

    Manifest.model_validate(manifest)
    assert "file_hashes" not in manifest
    assert executed["versions"]["file_hashes"]
    report = read(root / "report.json")
    assert report["gate"] == "blocked"  # Injected tool failure retained.
    assert all(row["cost_usd"] is None and row["total_tokens"] is None for row in report["cases"])
    assert len(report["safety"]["unmeasured"]) > 0
    entry = executed["cases"][0]
    trace = root / entry["trace"]["path"]
    trace.unlink()
    assert module.verify_run(root / "run-index.json")["valid"] is False


async def test_binding_hash_mismatch_cannot_verify(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    root = Path(executed["artifact_dir"])
    path = root / executed["cases"][0]["observation"]["path"]
    path.write_text("{}", encoding="utf-8")
    assert api().verify_run(root / "run-index.json")["valid"] is False


def test_cli_runs_eight_and_refuses_incompatible_options(tmp_path):
    api()
    command = [
        sys.executable,
        "evals/evaluate_enterprise.py",
        "--run-scenarios",
        str(ROOT / "cases.json"),
        "--artifacts-dir",
        str(tmp_path / "runs"),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    index = next((tmp_path / "runs").glob("*/run-index.json"))
    assert len(read(index)["cases"]) == 8
    incompatible = subprocess.run(
        command + ["--output", str(tmp_path / "wrong.json")], capture_output=True, text=True
    )
    assert incompatible.returncode == 1
    assert not (tmp_path / "wrong.json").exists()


async def test_verify_recomputes_scores_and_native_trace_bindings(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    root = Path(executed["artifact_dir"])
    from anlan.evaluation import evaluate_bundle
    from anlan.evaluation.offline_fixtures import digest

    index = read(root / "run-index.json")
    bundle = read(root / "bundle.json")
    bundle["cases"][0]["safety"]["stale_revision"]["status"] = "pass"
    (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(evaluate_bundle(bundle)), encoding="utf-8")
    for name in ("bundle", "report"):
        index[name]["sha256"] = digest((root / f"{name}.json").read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_run(root / "run-index.json")["valid"] is False


async def test_verify_rejects_forged_native_run_in_trace(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.offline_fixtures import digest

    root = Path(executed["artifact_dir"])
    index = read(root / "run-index.json")
    path = root / index["cases"][0]["trace"]["path"]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    record = next(
        r
        for r in records
        if r["producer"] == "native" and r["payload"]["event"] == "agent_tool_finished"
    )
    record["payload"]["run_id"] = "invented-native-run"
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    index["cases"][0]["trace"]["sha256"] = digest(path.read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_run(root / "run-index.json")["valid"] is False


async def test_malformed_and_missing_stimulus_never_gets_safety_pass(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.scoring import score_observation

    row = observation(executed, "knowledge-current")
    spec = next(
        s for s in api().load_catalog(ROOT / "cases.json").cases if s.case_id == row["case_id"]
    )
    malformed = copy.deepcopy(row)
    malformed["native"]["unexpected"] = "bad"
    assert score_observation(spec, malformed)["safety"]["invalid_knowledge"]["status"] == "pending"
    absent = copy.deepcopy(row)
    absent["calls"] = []
    assert score_observation(spec, absent)["safety"]["invalid_knowledge"]["status"] == "pending"
    changed = copy.deepcopy(row)
    changed["inputs"]["authority"]["withdrawal"]["withdrawn"] = True
    assert score_observation(spec, changed)["safety"]["invalid_knowledge"]["status"] == "pending"


async def test_malformed_results_preserve_error_instead_of_crashing(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.scoring import score_observation

    row = observation(executed, "tool-error")
    spec = next(
        s for s in api().load_catalog(ROOT / "cases.json").cases if s.case_id == row["case_id"]
    )
    row["native"]["results"] = None
    result = score_observation(spec, row)
    assert result["structure"]["status"] == "fail"
    assert "native_schema_invalid" in result["errors"]


async def test_cannot_erase_tool_error_by_rehashing_bundle(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation import evaluate_bundle
    from anlan.evaluation.offline_fixtures import digest

    root = Path(executed["artifact_dir"])
    index = read(root / "run-index.json")
    bundle = read(root / "bundle.json")
    row = next(r for r in bundle["cases"] if r["case_id"].endswith("tool-error"))
    assert "tool:data_error" in row["errors"]
    row["errors"] = []
    (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(evaluate_bundle(bundle)), encoding="utf-8")
    for name in ("bundle", "report"):
        index[name]["sha256"] = digest((root / f"{name}.json").read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_run(root / "run-index.json")["valid"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"stop_reason": "invented_protocol_state"},
        {"summary": {"arbitrary": "dict"}},
    ],
)
async def test_invalid_protocol_values_are_structurally_invalid(tmp_path, monkeypatch, change):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.scoring import score_observation

    row = observation(executed, "fact-normal")
    spec = next(
        s for s in api().load_catalog(ROOT / "cases.json").cases if s.case_id == row["case_id"]
    )
    row["native"].update(change)
    assert score_observation(spec, row)["structure"]["status"] == "fail"


async def test_replacing_whole_trace_with_matching_shell_cannot_verify(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.offline_fixtures import digest

    root = Path(executed["artifact_dir"])
    index = read(root / "run-index.json")
    entry = index["cases"][0]
    path = root / entry["trace"]["path"]
    fake = {
        "case_id": entry["case_id"],
        "case_run_id": entry["case_run_id"],
        "eval_run_id": index["eval_run_id"],
        "producer": "native",
        "payload": {"run_id": "unrelated-run", "event": "made_up"},
    }
    path.write_text(json.dumps(fake) + "\n", encoding="utf-8")
    entry["trace"]["sha256"] = digest(path.read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_run(root / "run-index.json")["valid"] is False


async def test_invalid_fixture_rejected_before_any_execution(tmp_path, monkeypatch):
    module = api()
    original = module.fixture_path
    broken = tmp_path / "broken-document.json"
    broken.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "fixture_path",
        lambda relative: broken if relative == "document.json" else original(relative),
    )
    with pytest.raises(ValidationError):
        await module.run_suite(ROOT / "cases.json", tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


async def test_cancellation_saves_partial_index_and_propagates(tmp_path, monkeypatch):
    import asyncio

    module = api()

    async def cancelled(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(module, "run_case", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await module.run_suite(ROOT / "cases.json", tmp_path / "runs")
    path = next((tmp_path / "runs").glob("*/run-index.json"))
    assert read(path)["status"] == "partial"
    assert module.verify_run(path)["valid"] is False
    assert not (path.parent / "report.json").exists()


async def test_existing_run_directory_is_never_overwritten(tmp_path, monkeypatch):
    module = api()
    monkeypatch.setattr(module, "uuid4", lambda: "existing-run")
    directory = tmp_path / "runs" / "existing-run"
    directory.mkdir(parents=True)
    marker = directory / "manifest.json"
    marker.write_text("preserve original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await module.run_suite(ROOT / "cases.json", tmp_path / "runs")
    assert marker.read_text(encoding="utf-8") == "preserve original"


async def test_trace_model_step_must_match_native_attempt(tmp_path, monkeypatch):
    executed = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.offline_fixtures import digest

    root = Path(executed["artifact_dir"])
    index = read(root / "run-index.json")
    entry = index["cases"][0]
    path = root / entry["trace"]["path"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    next(row for row in rows if row["payload"]["event"] == "model_step_finished")["payload"][
        "step"
    ] = 99
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    entry["trace"]["sha256"] = digest(path.read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_run(root / "run-index.json")["valid"] is False
