"""Host-owned personnel relationships and capability-specific frozen grants."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import uuid4

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from anlan.common.models import Identity
from anlan.tools.contracts import ObjectId
from anlan.tools.dynamic_mcp.catalog import (
    CatalogEntry,
    CatalogLease,
    CatalogScope,
    CatalogSnapshot,
    FrozenModel,
)
from anlan.tools.dynamic_mcp.contracts import Capability, CapabilityRequest
from anlan.tools.policy import FrozenTaskGrant

PERSONNEL_CAPABILITIES = (
    "contractor.qualification.query",
    "person.training.query",
    "person.access.query",
)


class Contractor(FrozenModel):
    name: str = Field(min_length=1, max_length=300, strict=True)
    factory_ids: tuple[ObjectId, ...] = Field(min_length=1)


class Person(Contractor):
    contractor_id: ObjectId


class PersonnelGrant(FrozenModel):
    factory_ids: tuple[ObjectId, ...]
    contractor_ids: tuple[ObjectId, ...]
    person_ids: tuple[ObjectId, ...]
    qualification_categories: tuple[ObjectId, ...]
    training_categories: tuple[ObjectId, ...]
    capabilities: tuple[Capability, ...]


class PersonnelRequest(FrozenModel):
    task_id: ObjectId
    factory_alias: str = Field(min_length=1, max_length=300, strict=True)
    contractor_id: ObjectId | None = None
    contractor_name: str | None = Field(default=None, min_length=1, max_length=300, strict=True)
    person_id: ObjectId | None = None
    person_name: str | None = Field(default=None, min_length=1, max_length=300, strict=True)
    qualification_category: ObjectId
    training_category: ObjectId
    question: str = Field(min_length=1, max_length=4000, strict=True)

    @model_validator(mode="after")
    def selectors(self):
        if not (self.contractor_id or self.contractor_name) or not (
            self.person_id or self.person_name
        ):
            raise ValueError("explicit_object_selector_required")
        return self


@dataclass(frozen=True)
class PersonnelPolicy:
    policy_version: str
    tenant_id: str
    directory_version: str
    factories: Mapping[str, tuple[str, ...]]
    contractors: Mapping[str, Contractor]
    persons: Mapping[str, Person]
    users: Mapping[str, PersonnelGrant]

    def __post_init__(self):
        for value in (self.policy_version, self.tenant_id, self.directory_version):
            TypeAdapter(ObjectId).validate_python(value)
        factories = {}
        for key, aliases in self.factories.items():
            TypeAdapter(ObjectId).validate_python(key)
            if isinstance(aliases, str) or not aliases:
                raise ValueError("invalid_policy")
            factories[key] = tuple(aliases)
            if any(not isinstance(a, str) or not a or len(a) > 300 for a in factories[key]):
                raise ValueError("invalid_policy")
        object.__setattr__(self, "factories", MappingProxyType(factories))
        for field, model in (
            ("contractors", Contractor),
            ("persons", Person),
            ("users", PersonnelGrant),
        ):
            frozen = {}
            for key, value in getattr(self, field).items():
                TypeAdapter(ObjectId).validate_python(key)
                frozen[key] = model.model_validate_json(value.model_dump_json())
            object.__setattr__(self, field, MappingProxyType(frozen))


class PersonnelSnapshot(FrozenModel):
    task_id: ObjectId
    run_id: ObjectId
    correlation_id: ObjectId
    revision: int = Field(ge=1, strict=True)
    identity: Identity
    query_at: AwareDatetime
    policy_version: str
    directory_version: str
    catalog_id: ObjectId
    contractor_id: ObjectId
    person_id: ObjectId
    factory_id: ObjectId
    qualification_category: ObjectId
    training_category: ObjectId
    question: str
    required_capabilities: tuple[Capability, ...]
    catalog: CatalogSnapshot
    entries: tuple[CatalogEntry, ...]
    requests: tuple[tuple[str, str], ...]
    leases: tuple[tuple[str, CatalogLease], ...]

    @property
    def task_grant(self):
        return FrozenTaskGrant(self.identity, self.requests)


def _resolve(kind, directory, object_id, name):
    if object_id is not None:
        if object_id not in directory:
            raise ValueError("access_denied")
        if name is not None and directory[object_id].name != name:
            raise ValueError("object_name_mismatch")
        return object_id
    candidates = [key for key, value in directory.items() if value.name == name]
    if not candidates:
        raise ValueError("unknown_" + kind)
    if len(candidates) != 1:
        raise ValueError("ambiguous_" + kind)
    return candidates[0]


async def prepare_personnel(service, identity, request, policy, registry, query_at):
    task = await service.get(identity, request.task_id)
    request = PersonnelRequest.model_validate_json(request.model_dump_json())
    identity = Identity.model_validate_json(identity.model_dump_json())
    if query_at.tzinfo is None or query_at.utcoffset() is None:
        raise ValueError("invalid_query_at")
    if identity.tenant_id != policy.tenant_id or identity.user_id not in policy.users:
        raise ValueError("access_denied")
    factories = [
        key for key, aliases in policy.factories.items() if request.factory_alias in aliases
    ]
    if not factories:
        raise ValueError("unknown_factory")
    if len(factories) != 1:
        raise ValueError("ambiguous_factory")
    factory_id = factories[0]
    contractor_id = _resolve(
        "contractor", policy.contractors, request.contractor_id, request.contractor_name
    )
    person_id = _resolve("person", policy.persons, request.person_id, request.person_name)
    person, contractor = policy.persons[person_id], policy.contractors[contractor_id]
    if (
        person.contractor_id != contractor_id
        or factory_id not in person.factory_ids
        or factory_id not in contractor.factory_ids
    ):
        raise ValueError("object_relationship_mismatch")
    grant = policy.users[identity.user_id]
    if (
        factory_id not in grant.factory_ids
        or contractor_id not in grant.contractor_ids
        or person_id not in grant.person_ids
        or request.qualification_category not in grant.qualification_categories
        or request.training_category not in grant.training_categories
        or not set(PERSONNEL_CAPABILITIES) <= set(grant.capabilities)
    ):
        raise ValueError("access_denied")
    catalog = await registry.load_catalog(
        CatalogScope(
            identity=identity,
            capabilities=PERSONNEL_CAPABILITIES,
            factory_ids=(factory_id,),
            policy_version=policy.policy_version,
        )
    )
    catalog = CatalogSnapshot.model_validate_json(catalog.model_dump_json())
    if catalog.tenant_id != identity.tenant_id or catalog.reader_user_id != identity.user_id:
        raise ValueError("catalog_scope_mismatch")
    aliases = set()
    for entry in catalog.entries:
        if (
            entry.tenant_id != identity.tenant_id
            or entry.factory_ids != (factory_id,)
            or entry.capability not in PERSONNEL_CAPABILITIES
        ):
            raise ValueError("catalog_scope_mismatch")
        if entry.alias in aliases:
            raise ValueError("source_conflict")
        aliases.add(entry.alias)
    selected, requests, leases = [], [], []
    for capability in PERSONNEL_CAPABILITIES:
        candidates = [e for e in catalog.entries if e.capability == capability]
        if not candidates:
            raise ValueError("missing_capability")
        if len(candidates) != 1:
            raise ValueError("source_conflict")
        entry = candidates[0]
        category = {
            PERSONNEL_CAPABILITIES[0]: request.qualification_category,
            PERSONNEL_CAPABILITIES[1]: request.training_category,
        }.get(capability)
        params = CapabilityRequest(
            capability=capability,
            factory_id=factory_id,
            objects=[contractor_id if capability == PERSONNEL_CAPABILITIES[0] else person_id],
            queried_at=query_at,
            category=category,
        )
        selected.append(entry)
        requests.append(
            (
                entry.alias,
                json.dumps(
                    params.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )
        )
        _, lease = await registry.resolve_business(identity, entry)
        lease = CatalogLease.model_validate_json(lease.model_dump_json())
        if (
            lease.tenant_id != identity.tenant_id
            or lease.service_id != entry.service_id
            or lease.generation != entry.generation
            or lease.config_revision != entry.config_revision
            or lease.discovery_id != entry.discovery_id
            or lease.target_policy_version != policy.policy_version
        ):
            raise ValueError("stale_generation")
        leases.append((entry.alias, lease))
    return PersonnelSnapshot(
        task_id=request.task_id,
        run_id=str(uuid4()),
        correlation_id=task.get("correlation_id", str(uuid4())),
        revision=task["revision"],
        identity=identity,
        query_at=query_at,
        policy_version=policy.policy_version,
        directory_version=policy.directory_version,
        catalog_id=catalog.catalog_id,
        contractor_id=contractor_id,
        person_id=person_id,
        factory_id=factory_id,
        qualification_category=request.qualification_category,
        training_category=request.training_category,
        question=request.question,
        required_capabilities=PERSONNEL_CAPABILITIES,
        catalog=catalog,
        entries=tuple(selected),
        requests=tuple(requests),
        leases=tuple(leases),
    )
