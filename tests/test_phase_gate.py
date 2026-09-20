import importlib.util
import json
from pathlib import Path

import pytest


def runner():
    spec = importlib.util.spec_from_file_location("phase_gate", Path("evals/phase_gate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_frozen_suite_runs_real_workflow_and_labels_archive_rescore(tmp_path):
    module = runner()
    result = await module.evaluate(tmp_path / "gate.json")
    assert result["status"] == "passed"
    assert result["workflow"]["cases"] == 8
    assert result["workflow"]["passed"] == 8
    assert result["requests_this_run"] == 0
    assert result["archive_rescore"]["mode"] == "archived_prediction_rescore"
    assert result["archive_rescore"]["exact_matches"] == 3
    assert result["archive_rescore"]["historical_total_tokens"] == 1184
    assert result["archive_rescore"]["model_issue_count"] == 1
    assert result["archive_rescore"]["rule_issue_count"] == 1
    with pytest.raises(FileExistsError):
        await module.evaluate(tmp_path / "gate.json")


def test_changed_fixture_is_rejected_before_execution(tmp_path):
    module = runner()
    manifest = json.loads(Path("evals/phase01-regression-v1/manifest.json").read_text())
    case_file = tmp_path / "cases.json"
    case_file.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="checksum"):
        module.load_verified(case_file, manifest["files"]["cases"]["sha256"], "json")


async def test_wrong_expected_state_is_retained_as_a_failed_case():
    module = runner()
    fixture = json.loads(Path("evals/phase01-regression-v1/cases.json").read_text(encoding="utf-8"))
    case = fixture["cases"][0]
    case["initial_expected"]["revision"] = 99
    result = await module.run_case(case, fixture["base_fields"])
    assert result["passed"] is False
    assert result["checks"][0]["passed"] is False
    assert result["checks"][0]["state"]["revision"] == 1


@pytest.mark.parametrize("corrupt_at", ["start", "resume"])
async def test_corrupted_checkpoint_cannot_pass_with_correct_return(monkeypatch, corrupt_at):
    module = runner()
    original = module.WorkflowService

    class CorruptAfterReturn(original):
        async def corrupt(self, result):
            record = self._registry.records[result["task_id"]]
            fields = {**result["fields"], "work_object_description": "SYNTHETIC：损坏字段"}
            await self._graph.aupdate_state(self._config(record), {"fields": fields})

        async def start(self, *args, **kwargs):
            result = await super().start(*args, **kwargs)
            if corrupt_at == "start":
                await self.corrupt(result)
            return result

        async def resume(self, identity, task_id, *args, **kwargs):
            result = await super().resume(identity, task_id, *args, **kwargs)
            if corrupt_at == "resume" and result["status"] == "awaiting_review":
                await self.corrupt(result)
            return result

    monkeypatch.setattr(module, "WorkflowService", CorruptAfterReturn)
    fixture = json.loads(Path("evals/phase01-regression-v1/cases.json").read_text(encoding="utf-8"))
    case = fixture["cases"][0 if corrupt_at == "start" else 1]
    result = await module.run_case(case, fixture["base_fields"])
    assert result["checks"][-1]["state"]["fields"]["work_object_description"] == (
        "SYNTHETIC：损坏字段")
    assert result["passed"] is False


async def test_graph_initialization_failure_is_saved_for_every_case(tmp_path, monkeypatch):
    module = runner()

    def broken_service(*args, **kwargs):
        raise RuntimeError("simulated graph initialization failure")

    monkeypatch.setattr(module, "WorkflowService", broken_service)
    output = tmp_path / "failed-suite.json"
    report = await module.evaluate(output)
    assert report["status"] == "failed"
    assert report["workflow"]["failed"] == 8
    assert all(row["checks"][-1]["error"] == "RuntimeError"
               for row in report["workflow"]["results"])
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"
