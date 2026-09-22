"""Event bodies are data; source identity and task binding are host-only."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from anlan.common.models import Identity
from anlan.workflows.event_contracts import SourceBinding, parse_event

NOW = datetime(2026, 9, 22, 4, tzinfo=UTC)
OWNER = Identity(tenant_id="synthetic-p5-tests", user_id="owner")


def payload(kind="helmet_missing", **changes):
    value = {"schema_version": "perception-event-v1", "data_origin": "SYNTHETIC",
             "event_id": "event-1", "sequence": 1, "kind": kind, "object_ref": "area-p5",
             "observed_at": (NOW - timedelta(seconds=10)).isoformat(),
             "expires_at": (NOW + timedelta(minutes=5)).isoformat(), "alarm_state": "active"}
    value.update({"confidence": 0.91} if kind == "helmet_missing" else
                 {"value": 22.5, "unit": "percent_lel"})
    return value | changes


def binding(state, source_id="camera-p5", kind="helmet_missing", **changes):
    return SourceBinding.model_validate({
        "identity": OWNER.model_dump(), "source_id": source_id, "kind": kind,
        "object_ref": "area-p5", "task_id": state["task_id"],
        "revision": state["revision"], "run_id": state["run_id"],
        "valid_from": NOW - timedelta(minutes=1), "valid_until": NOW + timedelta(hours=1),
    } | changes)


@pytest.mark.parametrize("kind", ["helmet_missing", "gas_abnormal"])
def test_two_explicit_synthetic_alarm_types(kind):
    event = parse_event(payload(kind))
    assert event.kind == kind and event.alarm_state == "active"


@pytest.mark.parametrize("changes", [
    {"tenant_id": "other"}, {"task_id": "injected"}, {"action": "silence_alarm"},
    {"alarm_state": "closed"}, {"data_origin": "REAL"}, {"sequence": True},
    {"sequence": "1"}, {"sequence": 0}, {"confidence": float("nan")},
    {"confidence": 1.1}, {"observed_at": "2026-09-22T04:00:00"},
    {"expires_at": "2026-09-21T04:00:00Z"}, {"object_ref": ""},
    {"schema_version": "unknown"}, {"event_id": "x" * 101},
])
def test_body_rejects_authority_invalid_time_and_unbounded_values(changes):
    with pytest.raises((ValueError, ValidationError)):
        parse_event(payload(**changes))


@pytest.mark.parametrize("changes", [{"value": -1}, {"value": float("inf")},
                                      {"unit": "ppm"}, {"confidence": 0.1}])
def test_sensor_contract_does_not_confuse_units_or_video_fields(changes):
    with pytest.raises(ValueError):
        parse_event(payload("gas_abnormal", **changes))


def test_binding_is_explicit_bounded_and_immutable():
    config = binding({"task_id": "task", "revision": 1, "run_id": "run"})
    with pytest.raises(ValidationError):
        config.task_id = "other"
    with pytest.raises(ValueError):
        binding({"task_id": "task", "revision": 1, "run_id": "run"},
                valid_until=NOW - timedelta(minutes=2))
