"""Shared identity and strict model primitives; no feature or infrastructure imports."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmpty = Annotated[str, StringConstraints(strict=True, strip_whitespace=True,
                                           min_length=1, max_length=500)]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Identity(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: NonEmpty
    user_id: NonEmpty
