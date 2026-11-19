"""Untrusted enterprise evidence and separate, host-owned receipt contracts.

Validation proves structure and request binding, never business safety or source authenticity.
"""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from anlan.common.models import StrictModel
from anlan.tools.contracts import ObjectId

Capability = Literal[
    "equipment.asset.query",
    "equipment.inspection.query",
    "equipment.fault.query",
    "contractor.qualification.query",
    "person.training.query",
    "person.access.query",
    "permit.ticket.query",
    "permit.overlap.query",
]
Text = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)
]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
# External protocol names are distinct from host/model aliases and business IDs.
OriginalToolName = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]


class Coverage(StrictModel):
    object_ids: list[ObjectId] = Field(min_length=1, max_length=100)
    start: AwareDatetime | None
    end: AwareDatetime | None

    @model_validator(mode="after")
    def interval(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("both window bounds are required")
        if self.start is not None and self.start >= self.end:
            raise ValueError("invalid window")
        return self


class CapabilityRequest(StrictModel):
    capability: Capability
    contract_version: Literal["1"] = "1"
    factory_id: ObjectId
    objects: list[ObjectId] = Field(min_length=1, max_length=100)
    queried_at: AwareDatetime
    coverage: Coverage | None = None
    category: ObjectId | None = None
    cursor: Text | None = None

    @model_validator(mode="after")
    def scope(self):
        if len(set(self.objects)) != len(self.objects):
            raise ValueError("duplicate objects")
        if self.coverage and not set(self.coverage.object_ids) <= set(self.objects):
            raise ValueError("coverage outside objects")
        if self.capability in {"contractor.qualification.query", "person.training.query"}:
            if self.category is None:
                raise ValueError("explicit qualification/training category required")
        if self.capability in {"permit.ticket.query", "permit.overlap.query"}:
            if self.coverage is None or self.coverage.start is None:
                raise ValueError("explicit permit time window required")
        return self


class BusinessRecord(StrictModel):
    object_id: ObjectId
    record_id: ObjectId
    original_status: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=300, pattern=r"\S")
    ]


class Asset(BusinessRecord):
    name: Text
    equipment_type: ObjectId
    factory_id: ObjectId
    status: Literal["in_use", "out_of_service", "unknown"]


class ValidityRecord(BusinessRecord):
    category: ObjectId
    valid_from: AwareDatetime | None
    valid_until: AwareDatetime | None

    @model_validator(mode="after")
    def interval(self):
        if (self.valid_from is None) != (self.valid_until is None):
            raise ValueError("incomplete validity interval")
        if self.valid_from is not None and self.valid_from >= self.valid_until:
            raise ValueError("invalid validity interval")
        return self


class Inspection(ValidityRecord):
    inspection_at: AwareDatetime | None
    status: Literal["valid", "expired", "failed", "unknown"]


class Fault(BusinessRecord):
    status: Literal["open", "closed", "unknown"]
    observed_at: AwareDatetime


class Qualification(ValidityRecord):
    status: Literal["active", "suspended", "revoked", "unknown"]


class Training(ValidityRecord):
    status: Literal["completed", "incomplete", "unknown"]
    applicable_factories: list[ObjectId] = Field(min_length=1, max_length=100)


class Access(ValidityRecord):
    factory_id: ObjectId
    status: Literal["granted", "denied", "revoked", "unknown"]


class Ticket(BusinessRecord):
    factory_id: ObjectId
    area_id: ObjectId
    work_type: ObjectId
    start: AwareDatetime
    end: AwareDatetime
    revision: ObjectId
    status: Literal["draft", "issued", "active", "closed", "cancelled", "unknown"]

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("invalid ticket window")
        return self


class Overlap(BusinessRecord):
    candidate_ticket: ObjectId
    area_id: ObjectId
    relationship_record_id: ObjectId
    start: AwareDatetime
    end: AwareDatetime
    status: Literal["candidate", "unknown"]

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("invalid overlap window")
        return self


PAYLOADS = {
    "equipment.asset.query": Asset,
    "equipment.inspection.query": Inspection,
    "equipment.fault.query": Fault,
    "contractor.qualification.query": Qualification,
    "person.training.query": Training,
    "person.access.query": Access,
    "permit.ticket.query": Ticket,
    "permit.overlap.query": Overlap,
}


class EvidenceSource(StrictModel):
    system_id: ObjectId
    record_id: ObjectId | None
    version: Text | None
    updated_at: AwareDatetime | None
    valid_from: AwareDatetime | None
    valid_until: AwareDatetime | None

    @model_validator(mode="after")
    def interval(self):
        if (self.valid_from is None) != (self.valid_until is None):
            raise ValueError("incomplete source interval")
        if self.valid_from is not None and self.valid_from >= self.valid_until:
            raise ValueError("invalid source interval")
        return self


class DynamicEvidence(StrictModel):
    schema_version: Literal["dynamic-evidence-v1"]
    capability: Capability
    contract_version: Literal["1"]
    data_origin: Literal["SYNTHETIC", "ENTERPRISE_DECLARED"]
    factory_id: ObjectId
    objects: list[ObjectId] = Field(min_length=1, max_length=100)
    queried_at: AwareDatetime
    outcome: Literal["ok", "unknown", "error"]
    reason: (
        Literal[
            "missing",
            "expired",
            "access_denied",
            "timeout",
            "cancelled",
            "disconnected",
            "contract_error",
            "unsupported",
            "source_conflict",
            "partial",
            "unknown_status",
        ]
        | None
    )
    data: list[
        Asset | Inspection | Fault | Qualification | Training | Access | Ticket | Overlap
    ] = Field(max_length=100)
    sources: list[EvidenceSource] = Field(max_length=100)
    complete: bool = Field(strict=True)
    next_cursor: Text | None
    coverage: Coverage

    @model_validator(mode="after")
    def business_contract(self):
        if len(set(self.objects)) != len(self.objects):
            raise ValueError("duplicate objects")
        if self.complete and self.next_cursor is not None:
            raise ValueError("complete result cannot have next cursor")
        if (self.outcome == "ok") != (self.reason is None):
            raise ValueError("non-ok requires reason; ok cannot have reason")
        if not set(self.coverage.object_ids) <= set(self.objects):
            raise ValueError("coverage outside objects")
        for record in self.data:
            if not isinstance(record, PAYLOADS[self.capability]):
                raise ValueError("wrong capability payload")
            if isinstance(record, Fault) and record.observed_at > self.queried_at:
                raise ValueError("future fault observation")
            if isinstance(record, (Ticket, Overlap)):
                if self.coverage.start is None or max(record.start, self.coverage.start) >= min(
                    record.end, self.coverage.end
                ):
                    raise ValueError("record outside query window")
            if isinstance(record, Training) and self.factory_id not in record.applicable_factories:
                raise ValueError("training outside factory")
            if record.object_id not in self.objects:
                raise ValueError("record outside objects")
            if hasattr(record, "factory_id") and record.factory_id != self.factory_id:
                raise ValueError("record outside factory")
        if self.outcome == "error" and self.data:
            raise ValueError("error must not carry business facts")
        return self

    @property
    def usable(self) -> bool:
        """Complete, sourced observation only; not a no-risk or approval predicate."""
        if self.outcome != "ok" or not self.complete or not self.sources:
            return False
        if set(self.coverage.object_ids) != set(self.objects):
            return False
        for source in self.sources:
            if source.version is None or source.updated_at is None:
                return False
            if source.updated_at > self.queried_at:
                return False
            if (
                source.valid_from is None
                or not source.valid_from <= self.queried_at < source.valid_until
            ):
                return False
        for record in self.data:
            if isinstance(record, ValidityRecord):
                if (
                    record.valid_from is None
                    or not record.valid_from <= self.queried_at < record.valid_until
                ):
                    return False
            if isinstance(record, Inspection) and (
                record.inspection_at is None or record.inspection_at > self.queried_at
            ):
                return False
        record_ids = {s.record_id for s in self.sources if s.record_id is not None}
        return all(r.record_id in record_ids and r.status != "unknown" for r in self.data)


class HostReceipt(StrictModel):
    service_id: ObjectId
    tool_name: Text
    call_id: ObjectId
    received_at: AwareDatetime
    config_version: ObjectId
    catalog_version: ObjectId
    route_version: ObjectId
    response_sha256: Digest
    selection_reason: Text


class ReceivedEvidence(StrictModel):
    remote: DynamicEvidence
    host: HostReceipt


def bind_evidence(evidence: DynamicEvidence, request: CapabilityRequest) -> DynamicEvidence:
    if (
        evidence.capability != request.capability
        or evidence.contract_version != request.contract_version
        or evidence.factory_id != request.factory_id
        or set(evidence.objects) != set(request.objects)
        or evidence.queried_at != request.queried_at
        or (request.coverage is not None and evidence.coverage != request.coverage)
    ):
        raise ValueError("evidence request binding mismatch")
    if request.category is not None and any(
        getattr(r, "category", None) != request.category for r in evidence.data
    ):
        raise ValueError("evidence category binding mismatch")
    return evidence


class StdioConnection(StrictModel):
    transport: Literal["stdio"]
    executable_ref: ObjectId
    argv: list[Text] = Field(max_length=20)
    credential_ref: ObjectId | None = None


class HttpConnection(StrictModel):
    transport: Literal["streamable_http"]
    target_ref: ObjectId
    credential_ref: ObjectId | None = None


class CapabilityBinding(StrictModel):
    capability: Capability
    contract_version: Literal["1"]
    tool_name: OriginalToolName
    factory_ids: list[ObjectId] = Field(min_length=1, max_length=100)


class Factory(StrictModel):
    factory_id: ObjectId
    aliases: list[Text] = Field(min_length=1, max_length=30)


class Registration(StrictModel):
    schema_version: Literal["dynamic-registration-v1"]
    data_origin: Literal["SYNTHETIC", "ENTERPRISE_DECLARED"]
    tenant_id: ObjectId
    service_id: ObjectId
    config_version: ObjectId
    state: Literal["registered", "discovered", "validated", "enabled", "disabled"]
    connection: Annotated[StdioConnection | HttpConnection, Field(discriminator="transport")]
    factories: list[Factory] = Field(min_length=1, max_length=100)
    bindings: list[CapabilityBinding] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def declarations(self):
        ids = [f.factory_id for f in self.factories]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate factory id")
        keys = [(b.capability, f) for b in self.bindings for f in b.factory_ids]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate capability scope")
        if any(not set(b.factory_ids) <= set(ids) for b in self.bindings):
            raise ValueError("undeclared factory")
        return self

    def validate_targets(
        self,
        *,
        executable_refs: set[str],
        http_targets: dict[str, str],
        stdio_argv: dict[str, list[str]],
    ):
        """Trusted administrator allowlists are separate from untrusted declarations."""
        if isinstance(self.connection, StdioConnection):
            if self.connection.executable_ref not in executable_refs:
                raise ValueError("untrusted executable reference")
            if stdio_argv.get(self.connection.executable_ref) != self.connection.argv:
                raise ValueError("untrusted argv profile")
        else:
            target = http_targets.get(self.connection.target_ref, "")
            parsed = urlsplit(target)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("untrusted HTTP target")
