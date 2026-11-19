import copy
import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path("evals/enterprise-eval-v2/knowledge-runner-v1")


def api():
    try:
        return importlib.import_module("anlan.evaluation.knowledge_runner")
    except ModuleNotFoundError:
        pytest.fail("native knowledge runner is not implemented")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def execute(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("knowledge evaluation attempted external IO")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    return await api().run_knowledge_suite(ROOT / "cases.json", tmp_path / "runs")


def get_case(index, suffix):
    entry = next(c for c in index["cases"] if c["case_id"].endswith(suffix))
    return read(Path(index["artifact_dir"]) / entry["observation"]["path"]), entry


def test_catalog_and_fixed_fixture_root_reject_scores_duplicates_and_outside(tmp_path):
    m = api()
    data = read(ROOT / "cases.json")
    with pytest.raises(ValidationError):
        m.Catalog.model_validate(data | {"scores": {}})
    with pytest.raises(ValidationError, match="duplicate"):
        m.Catalog.model_validate(data | {"cases": data["cases"] + [data["cases"][0]]})
    with pytest.raises(ValueError, match="trusted root"):
        m.load_catalog(tmp_path / "cases.json")
    with pytest.raises(ValueError):
        m.fixture_path("../manifest.json")


async def test_txt_bytes_real_parse_search_get_preserve_crlf_and_unpublished(tmp_path, monkeypatch):
    index = await execute(tmp_path, monkeypatch)
    obs, _ = get_case(index, "normal")
    assert [c["operation"] for c in obs["calls"]] == ["search", "get_clause"]
    assert obs["drafts"][0]["published"] is False
    assert obs["drafts"][0]["review_state"] == "needs_review"
    item = obs["calls"][1]["packet"]["items"][0]
    assert item["source_text"] == "SYNTHETIC clause alpha: isolate power before inspection.\r\n"
    assert item["locator"] == {"kind": "text", "line_start": 1, "line_end": 1}
    assert any(
        e["kind"] == "provider_finished" and e["data"]["route"] == "lexical" for e in obs["events"]
    )
    assert obs["diagnostics"]["source_and_quote_match"] is True
    assert obs["diagnostics"]["inputs_unchanged"] is True


async def test_actual_two_route_withdrawal_and_later_get_remains_denied(tmp_path, monkeypatch):
    index = await execute(tmp_path, monkeypatch)
    obs, _ = get_case(index, "withdrawal")
    events = obs["events"]
    lexical = next(
        e for e in events if e["kind"] == "provider_finished" and e["data"]["route"] == "lexical"
    )
    mutation = next(e for e in events if e["kind"] == "authority_mutation")
    vector = next(
        e for e in events if e["kind"] == "provider_started" and e["data"]["route"] == "vector"
    )
    assert lexical["seq"] < mutation["seq"] < vector["seq"]
    assert {c["key"]["logical_document_id"] for c in vector["data"]["candidates"]} == {"b"}
    assert all(i["key"]["logical_document_id"] == "b" for i in obs["calls"][0]["packet"]["items"])
    assert obs["calls"][1]["packet"]["items"] == []
    report = read(Path(index["artifact_dir"]) / "report.json")
    row = next(r for r in report["cases"] if r["case_id"].endswith("withdrawal"))
    assert row["safety"]["invalid_knowledge"]["status"] == "pass"
    assert row["semantic"]["status"] == row["human"]["status"] == "pending"
    assert row["safety"]["stale_revision"]["status"] == "pending"


async def test_actual_table_filter_and_derived_b3_not_workbook_parser(tmp_path, monkeypatch):
    index = await execute(tmp_path, monkeypatch)
    obs, _ = get_case(index, "table")
    assert obs["drafts"] == []
    packet = obs["calls"][0]["packet"]
    assert len(packet["table_rows"]) == 1
    cell = packet["table_rows"][0]["cells"][1]
    assert cell["value"] == "10" and cell["locator"]["cell"] == "B3"
    assert cell["locator"]["derivation"] == "derived_from_reviewed_ir"
    assert packet["items"][0]["table"]["units"] == ["", "m"]
    assert packet["items"][0]["table"]["footnotes"] == ["SYNTHETIC fixture footnote"]
    assert not any(e["kind"] == "provider_started" for e in obs["events"])
    assert obs["documents"][0]["lineage"]["quality"] == "unverified"


async def test_scoring_requires_real_dependencies_and_handles_malformed_packet(
    tmp_path, monkeypatch
):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "withdrawal")
    missing = copy.deepcopy(obs)
    missing["events"] = [e for e in missing["events"] if e["kind"] != "authority_mutation"]
    row = score_knowledge_observation(missing, entry["observation"])
    assert row["safety"]["invalid_knowledge"]["status"] == "pending" and row["errors"]
    invalid = copy.deepcopy(obs)
    invalid["calls"][0]["packet"]["items"] = None
    row = score_knowledge_observation(invalid, entry["observation"])
    assert row["structure"]["status"] == "fail"
    assert row["safety"]["invalid_knowledge"]["status"] == "pending"
    leak = copy.deepcopy(obs)
    event = next(
        e
        for e in leak["events"]
        if e["kind"] == "provider_started" and e["data"]["route"] == "vector"
    )
    lexical = next(
        e
        for e in leak["events"]
        if e["kind"] == "provider_started" and e["data"]["route"] == "lexical"
    )
    event["data"]["candidates"] = lexical["data"]["candidates"]
    assert (
        score_knowledge_observation(leak, entry["observation"])["safety"]["invalid_knowledge"][
            "status"
        ]
        == "fail"
    )


async def test_verify_rejects_rehashed_scores_and_trace_payload(tmp_path, monkeypatch):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation import evaluate_bundle
    from anlan.evaluation.knowledge_contracts import digest

    root = Path(index["artifact_dir"])
    assert api().verify_knowledge_run(root / "run-index.json")["valid"] is True
    bundle = read(root / "bundle.json")
    bundle["cases"][0]["safety"]["stale_revision"]["status"] = "pass"
    (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(evaluate_bundle(bundle)), encoding="utf-8")
    for name in ("bundle", "report"):
        index[name]["sha256"] = digest((root / f"{name}.json").read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_knowledge_run(root / "run-index.json")["valid"] is False
    entry = index["cases"][0]
    path = root / entry["trace"]["path"]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["kind"] = "made_up"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    entry["trace"]["sha256"] = digest(path.read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_knowledge_run(root / "run-index.json")["valid"] is False


def test_cli_actual_three_scenarios(tmp_path):
    api()
    result = subprocess.run(
        [
            sys.executable,
            "evals/evaluate_knowledge_v2.py",
            "--catalog",
            str(ROOT / "cases.json"),
            "--artifacts-dir",
            str(tmp_path / "runs"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stderr + result.stdout
    index = next((tmp_path / "runs").glob("*/run-index.json"))
    report = read(index.parent / "report.json")
    assert report["gate"] == "pending" and report["coverage"]["observed_cases"] == 3
    assert all(c["cost_usd"] is None and c["total_tokens"] is None for c in report["cases"])


async def test_event_request_binding_and_table_filter_cannot_be_relabelled(tmp_path, monkeypatch):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "withdrawal")
    ledger = next(e for e in obs["events"] if e["kind"] == "ledger_read")
    ledger["request_id"] = "unrelated-request"
    result = score_knowledge_observation(obs, entry["observation"])
    assert result["safety"]["invalid_knowledge"]["status"] == "pending" and result["errors"]
    table, entry = get_case(index, "table")
    table["calls"][0]["params"]["filters"][0]["value"] = "0"
    event = next(e for e in table["events"] if e["kind"] == "api_started")
    event["data"]["params"] = copy.deepcopy(table["calls"][0]["params"])
    assert score_knowledge_observation(table, entry["observation"])["errors"]


async def test_cancel_keeps_partial_trace_and_existing_outputs_are_preserved(tmp_path, monkeypatch):
    import asyncio

    module = api()

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(module.LocalBM25, "rank", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await module.run_knowledge_suite(ROOT / "cases.json", tmp_path / "runs")
    path = next((tmp_path / "runs").glob("*/run-index.json"))
    assert read(path)["status"] == "partial"
    assert list(path.parent.glob("cases/*/trace.jsonl"))
    assert module.verify_knowledge_run(path)["valid"] is False


async def test_changed_filter_stimulus_is_not_accepted_with_old_result(tmp_path, monkeypatch):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "table")
    obs["calls"][0]["params"]["filters"][0]["value"] = "0"
    next(e for e in obs["events"] if e["kind"] == "api_started")["data"]["params"] = copy.deepcopy(
        obs["calls"][0]["params"]
    )
    assert score_knowledge_observation(obs, entry["observation"])["errors"]


async def test_static_inputs_and_existing_run_fail_before_execution(tmp_path, monkeypatch):
    module = api()
    original = module.fixture_path
    bad = tmp_path / "invalid.json"
    bad.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module, "fixture_path", lambda name: bad if name == "table-ir.json" else original(name)
    )
    with pytest.raises(ValidationError):
        await module.run_knowledge_suite(ROOT / "cases.json", tmp_path / "runs")
    assert not (tmp_path / "runs").exists()
    monkeypatch.setattr(module, "fixture_path", original)
    monkeypatch.setattr(module, "uuid4", lambda: "existing-run")
    directory = tmp_path / "runs" / "existing-run"
    directory.mkdir(parents=True)
    marker = directory / "manifest.json"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await module.run_knowledge_suite(ROOT / "cases.json", tmp_path / "runs")
    assert marker.read_text(encoding="utf-8") == "keep"


def test_old_e2_sources_and_artifacts_remain_frozen():
    api()
    from anlan.evaluation.knowledge_contracts import digest
    from anlan.evaluation.runner import verify_run

    root = Path("evals/enterprise-eval-v2/runner-results/123a7fc5-343f-48f6-9aad-629ed41f2138")
    index = read(root / "run-index.json")
    for name in [
        "contracts.py",
        "report.py",
        "runner.py",
        "runner_contracts.py",
        "offline_fixtures.py",
        "scoring.py",
        "runner_verification.py",
    ]:
        path = "src/anlan/evaluation/" + name
        assert digest(Path(path).read_bytes()) == index["versions"]["file_hashes"][path]
    assert (
        digest(Path("evals/evaluate_enterprise.py").read_bytes())
        == index["versions"]["file_hashes"]["evals/evaluate_enterprise.py"]
    )
    assert verify_run(root / "run-index.json")["valid"] is True


async def test_independent_forged_trace_with_rehashed_observation_is_rejected(
    tmp_path, monkeypatch
):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_contracts import digest

    root = Path(index["artifact_dir"])
    obs, entry = get_case(index, "withdrawal")
    event = next(e for e in obs["events"] if e["kind"] == "ledger_read")
    event["request_id"] = "forged-request"
    op = root / entry["observation"]["path"]
    tp = root / entry["trace"]["path"]
    op.write_text(json.dumps(obs), encoding="utf-8")
    tp.write_text("\n".join(json.dumps(e) for e in obs["events"]) + "\n", encoding="utf-8")
    entry["observation"]["sha256"] = digest(op.read_bytes())
    entry["trace"]["sha256"] = digest(tp.read_bytes())
    (root / "run-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert api().verify_knowledge_run(root / "run-index.json")["valid"] is False


@pytest.mark.parametrize("target", ["selector", "resolver", "provider_version"])
async def test_source_selector_and_provider_versions_are_bound(tmp_path, monkeypatch, target):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "withdrawal")
    if target == "selector":
        obs["calls"][1]["params"]["selector"]["logical_document_id"] = "b"
        obs["calls"][1]["params"]["selector"]["document_version_id"] = "b-v1"
        start = [e for e in obs["events"] if e["kind"] == "api_started"][1]
        start["data"]["params"] = copy.deepcopy(obs["calls"][1]["params"])
    elif target == "resolver":
        for e in obs["events"]:
            if e["kind"] == "resolver_finished":
                e["data"]["block"] = {"fake": "wrong source"}
    else:
        next(e for e in obs["events"] if e["kind"] == "provider_started")["data"]["version"] = (
            "made-up-version"
        )
    row = score_knowledge_observation(obs, entry["observation"])
    assert row["safety"]["invalid_knowledge"]["status"] == "pending" and row["errors"]


@pytest.mark.parametrize(
    "target", ["missing_resolvers", "release_metadata", "revoked_related_key", "table_cell"]
)
async def test_complete_resolver_release_and_revoked_reference_binding(
    tmp_path, monkeypatch, target
):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_contracts import canonical, digest
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "table" if target == "table_cell" else "withdrawal")
    if target == "missing_resolvers":
        obs["events"] = [e for e in obs["events"] if not e["kind"].startswith("resolver_")]
        for i, e in enumerate(obs["events"]):
            e["seq"] = i
    else:
        packet = obs["calls"][0]["packet"]
        if target == "release_metadata":
            packet["items"][0]["release_fingerprint"] = "f" * 64
            packet["items"][0]["acl_revision"] = 999
        elif target == "revoked_related_key":
            lexical = next(e for e in obs["events"] if e["kind"] == "provider_started")
            key = next(
                c["key"]
                for c in lexical["data"]["candidates"]
                if c["key"]["logical_document_id"] == "a"
            )
            packet["issues"][0]["related_key"] = key
        else:
            packet["table_rows"][0]["cells"][0]["value"] = "invented-item"
        next(e for e in obs["events"] if e["kind"] == "api_finished")["data"]["packet_sha256"] = (
            digest(canonical(packet))
        )
    row = score_knowledge_observation(obs, entry["observation"])
    if target == "revoked_related_key":
        assert row["safety"]["invalid_knowledge"]["status"] == "fail"
    else:
        assert row["errors"]
        assert row["safety"]["invalid_knowledge"]["status"] == "pending"


@pytest.mark.parametrize(
    "field",
    [
        "release_fingerprint",
        "acl_revision",
        "withdrawal_revision",
        "checked_at",
        "missing_get_ledger",
    ],
)
async def test_per_api_current_release_metadata_required(tmp_path, monkeypatch, field):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_contracts import canonical, digest
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "withdrawal")
    if field == "missing_get_ledger":
        request_id = obs["calls"][1]["request"]["request_id"]
        obs["events"] = [
            e
            for e in obs["events"]
            if not (e["kind"] == "ledger_read" and e["request_id"] == request_id)
        ]
        for i, e in enumerate(obs["events"]):
            e["seq"] = i
    else:
        item = obs["calls"][0]["packet"]["items"][0]
        item[field] = (
            "0" * 64
            if field == "release_fingerprint"
            else "2020-01-01T00:00:00Z"
            if field == "checked_at"
            else 999
        )
        next(e for e in obs["events"] if e["kind"] == "api_finished")["data"]["packet_sha256"] = (
            digest(canonical(obs["calls"][0]["packet"]))
        )
    row = score_knowledge_observation(obs, entry["observation"])
    assert row["safety"]["invalid_knowledge"]["status"] == "pending" and row["errors"]


@pytest.mark.parametrize("surface", ["related_key", "audit"])
async def test_later_denial_cannot_leak_revoked_identifiers(tmp_path, monkeypatch, surface):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_contracts import canonical, digest
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "withdrawal")
    lexical = next(e for e in obs["events"] if e["kind"] == "provider_started")
    key = next(
        c["key"] for c in lexical["data"]["candidates"] if c["key"]["logical_document_id"] == "a"
    )
    packet = obs["calls"][1]["packet"]
    if surface == "related_key":
        packet["issues"].append({"code": "projection_missing", "related_key": key})
    else:
        packet["audit"].append(
            {"stage": "test", "decision_code": "retained", "key_digest": digest(canonical(key))}
        )
    [e for e in obs["events"] if e["kind"] == "api_finished"][1]["data"]["packet_sha256"] = digest(
        canonical(packet)
    )
    assert (
        score_knowledge_observation(obs, entry["observation"])["safety"]["invalid_knowledge"][
            "status"
        ]
        == "fail"
    )


@pytest.mark.parametrize("field", ["source_uri", "title", "ledger_checked_at"])
async def test_source_identity_and_authority_read_arguments_are_bound(tmp_path, monkeypatch, field):
    index = await execute(tmp_path, monkeypatch)
    from anlan.evaluation.knowledge_contracts import canonical, digest
    from anlan.evaluation.knowledge_scoring import score_knowledge_observation

    obs, entry = get_case(index, "withdrawal")
    if field == "ledger_checked_at":
        next(e for e in obs["events"] if e["kind"] == "ledger_read")["data"]["checked_at"] = (
            "2020-01-01T00:00:00+00:00"
        )
    else:
        packet = obs["calls"][0]["packet"]
        packet["items"][0][field] = (
            "synthetic://forged-source" if field == "source_uri" else "forged title"
        )
        next(e for e in obs["events"] if e["kind"] == "api_finished")["data"]["packet_sha256"] = (
            digest(canonical(packet))
        )
    row = score_knowledge_observation(obs, entry["observation"])
    assert row["safety"]["invalid_knowledge"]["status"] == "pending" and row["errors"]
