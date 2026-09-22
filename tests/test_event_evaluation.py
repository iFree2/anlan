import importlib.util
import json
from copy import deepcopy
from pathlib import Path


def test_replay_rejects_missing_type_wrong_revision_and_changed_alarm():
    spec = importlib.util.spec_from_file_location("evaluate_events", "evals/evaluate_events.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = json.loads(Path(
        "docs/phases/phase-05-events-service/evidence/wp01/replay-v1.json"
    ).read_text(encoding="utf-8"))["rows"]
    assert module.replay_passes(rows)
    assert not module.replay_passes(rows[:1])
    changed = deepcopy(rows)
    changed[0]["processed"]["raw"]["alarm_state"] = "closed"
    assert not module.replay_passes(changed)
    changed = deepcopy(rows)
    changed[0]["processed"]["result"]["revision"] += 1
    assert not module.replay_passes(changed)
    changed = deepcopy(rows)
    changed[0]["material_unchanged"] = False
    assert not module.replay_passes(changed)
