import importlib.util
import json
from copy import deepcopy
from pathlib import Path


def test_chain_score_rejects_failed_model_stale_version_and_changed_alarm():
    spec = importlib.util.spec_from_file_location(
        "evaluate_perception", "evals/evaluate_perception.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = Path("docs/phases/phase-05-events-service/evidence/wp02")
    scripted = json.loads((evidence / "scripted-v2.json").read_text(encoding="utf-8"))
    live = json.loads((evidence / "live-v1.json").read_text(encoding="utf-8"))
    assert all(module.chain_passes(row) for row in scripted["rows"])
    assert not any(module.chain_passes(row) for row in live["rows"])
    changed = deepcopy(scripted["rows"][0])
    changed["raw_unchanged"] = False
    assert not module.chain_passes(changed)
    changed = deepcopy(scripted["rows"][0])
    changed["follow_up"]["material_revision"] = 1
    assert not module.chain_passes(changed)
