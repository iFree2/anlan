"""Strict object selection contracts; authority always comes from the host."""

from typing import Annotated

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from anlan.common.models import Identity, NonEmpty, StrictModel
from anlan.tools.contracts import FactReferences, ObjectId

PositiveRevision = Annotated[int, Field(strict=True, ge=1)]


class BindingCommand(FactReferences):
    request_id: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=500, pattern=r"\S")
    ]
    expected_material_revision: PositiveRevision
    expected_binding_revision: int = Field(strict=True, ge=0)


class BindingRecord(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: NonEmpty
    binding_revision: PositiveRevision
    material_revision_at_confirmation: PositiveRevision
    references: FactReferences
    confirmed_by: Identity
    confirmed_at: AwareDatetime


class PrecheckPolicy(StrictModel):
    task_id: NonEmpty
    required: bool = Field(strict=True)
    legacy_completed: bool = Field(strict=True)

    @model_validator(mode="after")
    def consistent_policy(self):
        if self.required == self.legacy_completed:
            raise ValueError("Policy must require checks or preserve historical completion")
        return self


class EvidenceKey(StrictModel):
    task_id: NonEmpty
    material_revision: PositiveRevision
    binding_revision: PositiveRevision
    application_version: PositiveRevision


class RecheckCommand(StrictModel):
    request_id: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500,
                                               pattern=r'\S')]
    expected_material_revision: PositiveRevision
    expected_binding_revision: PositiveRevision
    expected_application_version: PositiveRevision
    reason: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500,
                                           pattern=r'\S')]


class CatalogQualification(StrictModel):
    qualification_type: ObjectId
    label: NonEmpty


class CatalogWorker(StrictModel):
    worker_id: ObjectId
    label: NonEmpty
    qualification_types: list[CatalogQualification] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_types(self):
        keys = [item.qualification_type for item in self.qualification_types]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate qualification type")
        return self


class CatalogArea(StrictModel):
    area_id: ObjectId
    label: NonEmpty


class ObjectCatalog(StrictModel):
    workers: list[CatalogWorker] = Field(default_factory=list, max_length=1000)
    areas: list[CatalogArea] = Field(default_factory=list, max_length=1000)


class PrecheckCatalog(ObjectCatalog):
    tenant_id: NonEmpty

    @model_validator(mode="after")
    def unambiguous_metadata(self):
        for keys in ([w.worker_id for w in self.workers], [a.area_id for a in self.areas]):
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate catalog object")
        labels = {}
        for worker in self.workers:
            for qualification in worker.qualification_types:
                key = qualification.qualification_type
                if key in labels and labels[key] != qualification.label:
                    raise ValueError("Conflicting qualification labels")
                labels[key] = qualification.label
        return self
