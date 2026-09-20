"""工具参数、合成来源与证据合同。时间统一使用带时区时间。"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from anlan.contracts import StrictModel

ObjectId = Annotated[str, StringConstraints(
    strict=True, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]


class WorkerQuery(StrictModel):
    worker_id: ObjectId
    qualification_type: ObjectId


class AreaQuery(StrictModel):
    area_id: ObjectId


class FactReferences(WorkerQuery, AreaQuery):
    pass


class AccessGrant(StrictModel):
    tenant_id: ObjectId
    user_id: ObjectId
    worker_ids: list[ObjectId]
    area_ids: list[ObjectId]


class AccessData(StrictModel):
    data_origin: Literal["SYNTHETIC"]
    version: ObjectId
    records: list[AccessGrant]


class Record(StrictModel):
    tenant_id: ObjectId
    record_id: ObjectId
    object_id: ObjectId
    observed_at: AwareDatetime
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_from >= self.valid_until:
            raise ValueError("invalid time interval")
        return self


class Qualification(Record):
    qualification_type: ObjectId
    status: Literal["active", "suspended", "revoked"]


class Area(Record):
    status: Literal["normal", "restricted", "closed"]


class FactData(StrictModel):
    data_origin: Literal["SYNTHETIC"]
    version: ObjectId
    records: list[Qualification] | list[Area]

    @model_validator(mode="after")
    def unique_records(self):
        keys = [(r.tenant_id, r.object_id, getattr(r, "qualification_type", None))
                for r in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate fact key")
        return self


class Source(StrictModel):
    resource: str
    version: str
    sha256: str
    record_id: str | None = None
    observed_at: AwareDatetime | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class ToolResult(StrictModel):
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"
    tool: Literal["query_worker_qualification", "query_area_status"]
    object_id: str | None
    queried_at: AwareDatetime
    outcome: Literal["ok", "unknown", "error"]
    reason: Literal[
        "missing", "expired", "not_yet_valid", "not_applicable", "invalid_parameters",
        "access_denied", "timeout", "data_error",
    ] | None = None
    source: Source | None = None
    facts: dict[str, str] | None = None
    message: str
    elapsed_ms: float = Field(ge=0)
