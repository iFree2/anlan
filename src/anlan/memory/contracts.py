"""Pure synthetic preference vocabulary and feedback contracts."""
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from anlan.common.models import NonEmpty, StrictModel

PREFERENCES = {
    "detail_level": frozenset({"brief", "detailed"}),
    "presentation_order": frozenset({"unknowns_first", "sources_first"}),
}

class MemoryConflict(ValueError):
    """Stale revision, incompatible source or disallowed transition; nothing committed."""

class Feedback(StrictModel):
    data_origin: Literal["SYNTHETIC"]
    source_ref: NonEmpty
    version: int = Field(strict=True, ge=1)
    key: Literal["detail_level", "presentation_order"]
    value: str = Field(strict=True, max_length=40)
    observed_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def check_preference(self):
        if self.value not in PREFERENCES[self.key]:
            raise ValueError("Preference value is not allowlisted")
        if self.observed_at >= self.expires_at:
            raise ValueError("Feedback requires a positive validity interval")
        return self
