import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals/quality-v1/manifest.json"


def fixture_root(tmp_path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        target = tmp_path / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / entry["path"]).read_bytes())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_recorded_failures_stay_unavailable_and_success_replays_without_network(monkeypatch):
    import httpx

    from anlan.workflows.quality import inspect_records, load_corpus, replay_records

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline replay attempted HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", forbidden)
    records = load_corpus(MANIFEST, ROOT)
    assert len(records) == 11
    summary = inspect_records(records)
    assert "messages" not in json.dumps(summary) and "candidate" not in summary[0]
    rows = {r["id"]: r for r in replay_records(records, split="dev")}
    assert rows["old-helmet"]["actual"] == "not_replayable"
    assert rows["old-gas"]["actual"] == "not_replayable"
    assert rows["new-helmet"]["actual"] == "accepted"
    assert rows["new-helmet"]["feedback_origin"] == "synthetic_replay_actor"
    assert rows["dev-duplicate"]["actual"] == "rejected"
    assert all(row["matches_expected"] for row in rows.values())


@pytest.mark.parametrize("change", ["hash", "origin", "family", "selection", "source", "escape"])
def test_corpus_rejects_tampering_non_synthetic_and_split_leakage(tmp_path, change):
    from anlan.workflows.quality import load_corpus

    path, manifest = fixture_root(tmp_path)
    first = manifest["entries"][0]
    if change == "family":
        manifest["entries"][2]["family"] = first["family"]
    elif change == "selection":
        other = first | {"id": "disguised", "family": "different", "split": "holdout"}
        manifest["entries"].append(other)
    elif change == "source":
        manifest["entries"][1]["split"] = "holdout"
    elif change == "escape":
        first["path"] = "../outside.json"
    else:
        source = tmp_path / first["path"]
        data = json.loads(source.read_text(encoding="utf-8"))
        data["data_origin"] = "REAL"
        source.write_text(json.dumps(data), encoding="utf-8")
        if change == "origin":
            new_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            for entry in manifest["entries"]:
                if entry["path"] == first["path"]:
                    entry["sha256"] = new_hash
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_corpus(path, tmp_path)


def test_unknown_duplicates_are_not_a_complete_unknown_list():
    from anlan.workflows.perception_contracts import build_context, validate_candidate

    case = json.loads((ROOT / "evals/quality-v1/dev.json").read_text(encoding="utf-8"))["cases"][0]
    with pytest.raises(ValueError):
        validate_candidate(case["candidate"], build_context(case["event"], case["bundle"]))


@pytest.mark.parametrize("body", ["[]", "null", "[" * 1100 + "]" * 1100],
                         ids=["array", "null", "deep_json"])
def test_cli_malformed_source_is_saved_as_failure_and_cannot_overwrite(tmp_path, body):
    path, manifest = fixture_root(tmp_path)
    entry = manifest["entries"][0]
    source = tmp_path / entry["path"]
    source.write_text(body, encoding="utf-8")
    for item in manifest["entries"]:
        if item["path"] == entry["path"]:
            item["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "out.json"
    command = [sys.executable, "-m", "anlan.interfaces.quality_cli", "inspect", "--manifest",
               str(path), "--root", str(tmp_path), "--output", str(out)]
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    first = subprocess.run(command, capture_output=True, env=env, timeout=20)
    assert first.returncode == 1
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "failed" and result["model_requests"] == 0
    before = out.read_bytes()
    second = subprocess.run(command, capture_output=True, env=env, timeout=20)
    assert second.returncode == 2 and out.read_bytes() == before
