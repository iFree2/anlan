"""Object references are strict business IDs, never client-supplied authority."""

import pytest
from pydantic import ValidationError


def command(**changes):
    return dict(request_id="bind-1", expected_material_revision=1,
                expected_binding_revision=0, worker_id="worker-a",
                qualification_type="welding", area_id="area-a") | changes


def test_binding_command_keeps_resources_separate_from_actor():
    from anlan.preflight.contracts import BindingCommand

    parsed = BindingCommand.model_validate(command())
    assert parsed.worker_id == "worker-a"
    assert "actor" not in parsed.model_dump()


@pytest.mark.parametrize("changes", [
    {"actor": "applicant"}, {"role": "admin"}, {"ready": True},
    {"expected_material_revision": True}, {"expected_material_revision": 0},
    {"expected_binding_revision": False}, {"expected_binding_revision": -1},
    {"expected_binding_revision": "1"}, {"worker_id": "张师傅"},
    {"area_id": "一号楼东侧"}, {"worker_id": " worker-a"},
    {"qualification_type": ""}, {"request_id": "   "},
])
def test_binding_command_rejects_injection_and_ambiguous_text(changes):
    from anlan.preflight.contracts import BindingCommand

    with pytest.raises(ValidationError):
        BindingCommand.model_validate(command(**changes))


def test_binding_record_has_independent_revision_and_real_confirmation():
    from anlan.preflight.contracts import BindingRecord, EvidenceKey, PrecheckPolicy

    record = BindingRecord.model_validate(dict(
        task_id="task", binding_revision=2, material_revision_at_confirmation=4,
        references={k: command()[k] for k in ("worker_id", "qualification_type", "area_id")},
        confirmed_by={"tenant_id": "tenant", "user_id": "applicant"},
        confirmed_at="2026-10-26T09:00:00+08:00"))
    assert record.binding_revision == 2
    assert record.material_revision_at_confirmation == 4
    with pytest.raises(ValidationError):
        BindingRecord.model_validate(record.model_dump() | {"binding_revision": True})
    with pytest.raises(ValidationError):
        BindingRecord.model_validate(record.model_dump() | {"confirmed_at": "2026-10-26"})
    assert EvidenceKey(task_id="task", material_revision=4, binding_revision=2,
                       application_version=1).binding_revision == 2
    assert PrecheckPolicy(task_id="task", required=False, legacy_completed=True).legacy_completed
    for values in [(True, True), (False, False), (1, False)]:
        with pytest.raises(ValidationError):
            PrecheckPolicy(task_id="task", required=values[0], legacy_completed=values[1])
