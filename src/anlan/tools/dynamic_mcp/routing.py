"""Host-owned tenant routing and immutable inquiry authorization snapshots."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import uuid4

from pydantic import AwareDatetime, Field

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

EQUIPMENT_CAPABILITIES = (
    "equipment.asset.query",
    "equipment.inspection.query",
    "equipment.fault.query",
)


class InquiryRequest(FrozenModel):
    task_id: ObjectId
    factory_alias: str = Field(min_length=1, max_length=300, strict=True)
    equipment_id: ObjectId
    question: str = Field(min_length=1, max_length=4000, strict=True)


class InquiryUserGrant(FrozenModel):
    """Explicit product of authorized factories, equipment IDs and capabilities."""

    factory_ids: tuple[ObjectId, ...]
    equipment_ids: tuple[ObjectId, ...]
    capabilities: tuple[Capability, ...]


@dataclass(frozen=True)
class InquiryPolicyConfig:
    policy_version: str
    tenant_id: str
    factory_directory_version: str
    factories: Mapping[str, tuple[str, ...]]
    users: Mapping[str, InquiryUserGrant]

    def __post_init__(self):
        for value in (self.policy_version, self.tenant_id, self.factory_directory_version):
            if not isinstance(value, str) or not value:
                raise ValueError("invalid_policy")
        factories = {}
        for factory_id, aliases in self.factories.items():
            if not isinstance(factory_id, str) or not factory_id or isinstance(aliases, str):
                raise ValueError("invalid_policy")
            aliases = tuple(aliases)
            if not aliases or any(not isinstance(a, str) or not a for a in aliases):
                raise ValueError("invalid_policy")
            factories[factory_id] = aliases
        users = {
            user: InquiryUserGrant.model_validate_json(grant.model_dump_json())
            for user, grant in self.users.items()
        }
        object.__setattr__(self, "factories", MappingProxyType(factories))
        object.__setattr__(self, "users", MappingProxyType(users))


class InquiryTaskSnapshot(FrozenModel):
    task_id: ObjectId
    run_id: ObjectId
    correlation_id: ObjectId
    revision: int = Field(ge=1, strict=True)
    identity: Identity
    query_at: AwareDatetime
    policy_version: str
    directory_version: str
    catalog_id: ObjectId
    equipment_id: ObjectId
    factory_id: ObjectId
    question: str
    required_capabilities: tuple[Capability, ...]
    catalog: CatalogSnapshot
    entries: tuple[CatalogEntry, ...]
    requests: tuple[tuple[str, str], ...]
    leases: tuple[tuple[str, CatalogLease], ...]

    @property
    def task_grant(self) -> FrozenTaskGrant:
        return FrozenTaskGrant(self.identity, self.requests)


async def prepare_inquiry(service, identity, request, policy, registry, query_at: datetime):
    """Check task access first, then authorize and freeze exactly one M2 source per cap."""
    task = await service.get(identity, request.task_id)
    request = InquiryRequest.model_validate_json(request.model_dump_json())
    identity = Identity.model_validate_json(identity.model_dump_json())
    if query_at.tzinfo is None or query_at.utcoffset() is None:
        raise ValueError("invalid_query_at")
    if identity.tenant_id != policy.tenant_id or identity.user_id not in policy.users:
        raise ValueError("access_denied")
    factories = [f for f, aliases in policy.factories.items() if request.factory_alias in aliases]
    if not factories:
        raise ValueError("unknown_factory")
    if len(factories) != 1:
        raise ValueError("ambiguous_factory")
    factory_id = factories[0]
    grant = policy.users[identity.user_id]
    if (
        factory_id not in grant.factory_ids
        or request.equipment_id not in grant.equipment_ids
        or not set(EQUIPMENT_CAPABILITIES) <= set(grant.capabilities)
    ):
        raise ValueError("access_denied")
    scope = CatalogScope(
        identity=identity,
        capabilities=EQUIPMENT_CAPABILITIES,
        factory_ids=(factory_id,),
        policy_version=policy.policy_version,
    )
    catalog = await registry.load_catalog(scope)
    catalog = CatalogSnapshot.model_validate_json(catalog.model_dump_json())
    if catalog.tenant_id != identity.tenant_id or catalog.reader_user_id != identity.user_id:
        raise ValueError("catalog_scope_mismatch")
    aliases = set()
    for entry in catalog.entries:
        if (
            entry.tenant_id != identity.tenant_id
            or entry.factory_ids != (factory_id,)
            or entry.capability not in EQUIPMENT_CAPABILITIES
        ):
            raise ValueError("catalog_scope_mismatch")
        if entry.alias in aliases:
            raise ValueError("source_conflict")
        aliases.add(entry.alias)
    selected, requests = [], []
    for capability in EQUIPMENT_CAPABILITIES:
        candidates = [entry for entry in catalog.entries if entry.capability == capability]
        if not candidates:
            raise ValueError("missing_capability")
        if len(candidates) > 1:
            raise ValueError("source_conflict")
        entry = candidates[0]
        params = CapabilityRequest(
            capability=capability,
            factory_id=factory_id,
            objects=[request.equipment_id],
            queried_at=query_at,
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
    leases = []
    for entry in selected:
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
    return InquiryTaskSnapshot(
        task_id=request.task_id,
        run_id=str(uuid4()),
        correlation_id=task.get("correlation_id", str(uuid4())),
        revision=task["revision"],
        identity=identity,
        query_at=query_at,
        policy_version=policy.policy_version,
        directory_version=policy.factory_directory_version,
        catalog_id=catalog.catalog_id,
        equipment_id=request.equipment_id,
        factory_id=factory_id,
        question=request.question,
        required_capabilities=EQUIPMENT_CAPABILITIES,
        catalog=catalog,
        entries=tuple(selected),
        requests=tuple(requests),
        leases=tuple(leases),
    )
