import json
import os
import subprocess
import sys

from anlan.evaluation import score_issues


def test_scoring_preserves_false_positives_misses_and_zero_denominators():
    scores = score_issues(
        [["work_location_description", "ambiguous"], ["attachment_description", "conflict"]],
        [["work_location_description", "ambiguous"], ["work_object_description", "missing"]],
    )
    assert scores == {"tp": 1, "fp": 1, "fn": 1, "precision": .5,
                      "recall": .5, "exact_match": False}
    assert score_issues([], []) == {"tp": 0, "fp": 0, "fn": 0, "precision": None,
                                    "recall": None, "exact_match": True}
    assert score_issues([], [["work_location_description", "ambiguous"]])["fn"] == 1


def test_offline_evaluation_keeps_known_semantic_miss_and_refuses_overwrite(tmp_path):
    output = tmp_path / "evaluation.json"
    command = [sys.executable, "evals/evaluate.py", "--mode", "offline",
               "--output", str(output)]
    kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "timeout": 30,
              "env": {**os.environ, "PYTHONUTF8": "1"}}
    result = subprocess.run(command, **kwargs)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "offline"
    assert [r["scores"]["exact_match"] for r in report["results"]] == [True, True, False]
    assert report["results"][-1]["scores"]["fn"] == 1
    original = output.read_bytes()
    assert subprocess.run(command, **kwargs).returncode == 2
    assert output.read_bytes() == original
