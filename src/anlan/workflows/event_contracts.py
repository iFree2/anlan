"""Versioned synthetic event bodies and trusted host bindings."""
import hashlib
import json
from datetime import UTC
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from anlan.common.models import Identity, StrictModel

EventKind = Literal["helmet_missing", "gas_abnormal"]
Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100,
                                              pattern=r"^[A-Za-z0-9_.:-]+$")]
Sequence = Annotated[int, Field(strict=True, ge=1, le=9223372036854775807)]


class EventBase(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["perception-event-v1"]
    data_origin: Literal["SYNTHETIC"]
    event_id: Identifier
    sequence: Sequence
    object_ref: Identifier
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    alarm_state: Literal["active"]

    @field_validator("observed_at", "expires_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self):
        if not 0 < (self.expires_at - self.observed_at).total_seconds() <= 900:
            raise ValueError("Event validity must be positive and at most 15 minutes")
        return self


class HelmetEvent(EventBase):
    kind: Literal["helmet_missing"]
    confidence: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


class GasEvent(EventBase):
    kind: Literal["gas_abnormal"]
    value: float = Field(strict=True, ge=0, le=1000, allow_inf_nan=False)
    unit: Literal["percent_lel"]


EVENT_ADAPTER = TypeAdapter(Annotated[HelmetEvent | GasEvent, Field(discriminator="kind")])


class SourceBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: Identity
    source_id: Identifier
    kind: EventKind
    object_ref: Identifier
    task_id: Identifier
    revision: Sequence
    run_id: Identifier
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.valid_from >= self.valid_until:
            raise ValueError("Source binding needs an ordered validity window")
        return self


class EventConflict(ValueError):
    """Immutable event identity has already been used for different content."""


def parse_event(payload):
    return EVENT_ADAPTER.validate_python(payload)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
