"""Sanitized discovery contracts and host-scoped immutable tool catalogs."""

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator

from anlan.common.models import Identity, StrictModel
from anlan.tools.contracts import ObjectId
from anlan.tools.dynamic_mcp.contracts import (
    PAYLOADS,
    Capability,
    CapabilityRequest,
    Digest,
    DynamicEvidence,
    OriginalToolName,
    Registration,
)

SCHEMA_PROFILE = "mcp-business-profile-v1"
_ANNOTATIONS = {"title", "description", "examples", "$comment"}
_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "$defs",
    "$ref",
    "anyOf",
    "enum",
    "const",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "format",
    "default",
}


def _json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def canonical_schema(schema: dict) -> str:
    """Accept only the bounded local profile; never evaluate regex or fetch refs.

    Property names are data, not keywords. Annotation removal therefore only happens
    at schema nodes, including nodes in properties/$defs/anyOf/items.
    """
    nodes = 0
    active = set()

    def budget(value, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 16 or nodes > 2048:
            raise ValueError("schema_unsupported")
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise ValueError("schema_unsupported")
            active.add(id(value))
            if isinstance(value, dict):
                if any(not isinstance(k, str) for k in value):
                    raise ValueError("schema_unsupported")
                children = value.values()
            else:
                children = value
            for child in children:
                budget(child, depth + 1)
            active.remove(id(value))
        elif value is not None and type(value) not in (str, int, float, bool):
            raise ValueError("schema_unsupported")
        elif type(value) is float and not math.isfinite(value):
            raise ValueError("schema_unsupported")

    budget(schema)
    if len(_json(schema).encode("utf-8")) > 65536:
        raise ValueError("oversized_result")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("schema_unsupported")

    def clean(node):
        if not isinstance(node, dict) or set(node) - _KEYWORDS - _ANNOTATIONS:
            raise ValueError("schema_unsupported")
        result = {}
        for key, value in node.items():
            if key in _ANNOTATIONS:
                continue
            if key in {"properties", "$defs"}:
                if not isinstance(value, dict):
                    raise ValueError("schema_unsupported")
                result[key] = {name: clean(child) for name, child in value.items()}
            elif key in {"items", "additionalProperties"}:
                if key == "additionalProperties" and isinstance(value, bool):
                    result[key] = value
                else:
                    result[key] = clean(value)
            elif key == "anyOf":
                if not isinstance(value, list) or not value:
                    raise ValueError("schema_unsupported")
                result[key] = [clean(child) for child in value]
            else:
                if key == "type" and value not in (
                    "object",
                    "array",
                    "string",
                    "integer",
                    "number",
                    "boolean",
                    "null",
                ):
                    raise ValueError("schema_unsupported")
                if key == "required" and (
                    not isinstance(value, list)
                    or any(not isinstance(v, str) for v in value)
                    or len(set(value)) != len(value)
                ):
                    raise ValueError("schema_unsupported")
                if key in {"pattern", "$ref"} and not isinstance(value, str):
                    raise ValueError("schema_unsupported")
                if key == "format" and value != "date-time":
                    raise ValueError("schema_unsupported")
                if key == "enum" and (not isinstance(value, list) or not value):
                    raise ValueError("schema_unsupported")
                if key in {"minItems", "maxItems", "minLength", "maxLength"} and (
                    type(value) is not int or value < 0
                ):
                    raise ValueError("schema_unsupported")
                if key in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"} and type(
                    value
                ) not in (int, float):
                    raise ValueError("schema_unsupported")
                result[key] = value
        return result

    cleaned = clean(schema)

    heights, visiting = {}, set()

    def refs(node, depth=0):
        # Memoize DAG paths: repeated references must not cause exponential work.
        if depth > 16 or id(node) in visiting:
            raise ValueError("schema_unsupported")
        if id(node) in heights:
            return heights[id(node)]
        visiting.add(id(node))
        children = []
        if "$ref" in node:
            ref = node["$ref"]
            # Restrict pointers to root definitions, as generated by our local models.
            if not ref.startswith("#/$defs/"):
                raise ValueError("schema_unsupported")
            name = ref[len("#/$defs/") :]
            if "/" in name or "~" in name or name not in cleaned.get("$defs", {}):
                raise ValueError("schema_unsupported")
            children.append(cleaned["$defs"][name])
        for key in ("properties", "$defs"):
            for child in node.get(key, {}).values():
                children.append(child)
        children.extend(node.get("anyOf", []))
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), dict):
                children.append(node[key])
        height = 1 + max((refs(child, depth + 1) for child in children), default=0)
        if height > 16:
            raise ValueError("schema_unsupported")
        visiting.remove(id(node))
        heights[id(node)] = height
        return height

    refs(cleaned)
    return _json(cleaned)


def expected_schemas(capability: Capability) -> tuple[dict, dict]:
    """Return fresh local schemas. Cross-field semantics remain M1 Pydantic's job."""
    if capability not in PAYLOADS:
        raise ValueError("schema_unsupported")
    schemas = (CapabilityRequest.model_json_schema(), DynamicEvidence.model_json_schema())
    for schema in schemas:
        schema["properties"]["capability"] = {"type": "string", "const": capability}
    return tuple(json.loads(canonical_schema(schema)) for schema in schemas)


class FrozenModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveredTool(FrozenModel):
    name: OriginalToolName
    input_schema_json: str
    output_schema_json: str | None = None

    @field_validator("input_schema_json", "output_schema_json")
    @classmethod
    def canonical(cls, value):
        if value is None:
            return value
        if len(value.encode("utf-8")) > 65536:
            raise ValueError("oversized_result")
        try:
            return canonical_schema(json.loads(value))
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("schema_unsupported") from exc


def sanitize_tool(
    name: str, input_schema: dict, output_schema: dict | None = None
) -> DiscoveredTool:
    return DiscoveredTool(
        name=name,
        input_schema_json=canonical_schema(input_schema),
        output_schema_json=None if output_schema is None else canonical_schema(output_schema),
    )


class DiscoverySnapshot(FrozenModel):
    discovery_id: ObjectId
    captured_generation: int = Field(ge=1)
    protocol_version: str = Field(min_length=1, max_length=100)
    server_name: str = Field(min_length=1, max_length=100)
    server_version: str = Field(min_length=1, max_length=100)
    discovered_at: AwareDatetime
    tools: tuple[DiscoveredTool, ...] = Field(max_length=50)
    digest: Digest

    @model_validator(mode="after")
    def bounded(self):
        if len({t.name for t in self.tools}) != len(self.tools):
            raise ValueError("discovery_incomplete")
        if len(self.model_dump_json().encode("utf-8")) > 524288:
            raise ValueError("oversized_result")
        if self.digest != _digest(self.model_dump(mode="json", exclude={"digest"})):
            raise ValueError("discovery_incomplete")
        return self


def make_discovery(
    *,
    discovery_id,
    captured_generation,
    protocol_version,
    server_name,
    server_version,
    discovered_at,
    tools,
    digest=None,
) -> DiscoverySnapshot:
    fields = dict(
        discovery_id=discovery_id,
        captured_generation=captured_generation,
        protocol_version=protocol_version,
        server_name=server_name,
        server_version=server_version,
        discovered_at=discovered_at,
        tools=tuple(tools),
    )
    # Timestamp serialization follows the actual validated storage representation.
    encoded = {
        **fields,
        "discovered_at": discovered_at.isoformat().replace("+00:00", "Z"),
        "tools": [t.model_dump(mode="json") for t in fields["tools"]],
    }
    return DiscoverySnapshot(**fields, digest=_digest(encoded))


class ValidatedTool(FrozenModel):
    original_name: OriginalToolName
    alias: str
    capability: Capability
    contract_version: Literal["1"]
    input_schema_digest: Digest
    output_schema_digest: Digest
    schema_profile: Literal["mcp-business-profile-v1"] = SCHEMA_PROFILE


class ValidationReport(FrozenModel):
    valid: bool
    tools: tuple[ValidatedTool, ...]
    error_codes: tuple[str, ...]
    digest: Digest
    schema_profile: Literal["mcp-business-profile-v1"] = SCHEMA_PROFILE
    registration_digest: Digest
    discovery_digest: Digest

    @model_validator(mode="after")
    def checked(self):
        if self.valid != (not self.error_codes) or (not self.valid and self.tools):
            raise ValueError("contract_mismatch")
        if self.digest != _digest(self.model_dump(mode="json", exclude={"digest"})):
            raise ValueError("contract_mismatch")
        return self


def tool_alias(
    service_id: str,
    original_name: str,
    *,
    tenant_id: str = "",
    capability: str = "",
    contract_version: str = "1",
) -> str:
    return "m_" + _digest([tenant_id, service_id, original_name, capability, contract_version])[:62]


def validate_discovery(registration: Registration, snapshot: DiscoverySnapshot) -> ValidationReport:
    registration = Registration.model_validate_json(registration.model_dump_json())
    try:
        snapshot = DiscoverySnapshot.model_validate_json(snapshot.model_dump_json())
    except ValueError:
        fields = dict(
            valid=False,
            tools=[],
            error_codes=["discovery_incomplete"],
            schema_profile=SCHEMA_PROFILE,
            registration_digest=_digest(registration.model_dump(mode="json")),
            discovery_digest=snapshot.digest,
        )
        return ValidationReport(**fields, digest=_digest(fields))
    found = {tool.name: tool for tool in snapshot.tools}
    errors, validated, aliases = set(), [], {}
    if len(found) != len(snapshot.tools):
        errors.add("discovery_incomplete")
    for binding in registration.bindings:
        tool = found.get(binding.tool_name)
        if tool is None or tool.output_schema_json is None:
            errors.add("contract_mismatch")
            continue
        inp, out = expected_schemas(binding.capability)
        if tool.input_schema_json != _json(inp) or tool.output_schema_json != _json(out):
            errors.add("contract_mismatch")
            continue
        key = (
            registration.tenant_id,
            registration.service_id,
            tool.name,
            binding.capability,
            binding.contract_version,
        )
        alias = tool_alias(
            registration.service_id,
            tool.name,
            tenant_id=registration.tenant_id,
            capability=binding.capability,
            contract_version=binding.contract_version,
        )
        if alias in aliases and aliases[alias] != key:
            errors.add("source_conflict")
            continue
        aliases[alias] = key
        item = ValidatedTool(
            original_name=tool.name,
            alias=alias,
            capability=binding.capability,
            contract_version=binding.contract_version,
            input_schema_digest=hashlib.sha256(tool.input_schema_json.encode()).hexdigest(),
            output_schema_digest=hashlib.sha256(tool.output_schema_json.encode()).hexdigest(),
        )
        if item not in validated:
            validated.append(item)
    fields = dict(
        valid=not errors,
        tools=tuple(validated) if not errors else (),
        error_codes=tuple(sorted(errors)),
        schema_profile=SCHEMA_PROFILE,
        registration_digest=_digest(registration.model_dump(mode="json")),
        discovery_digest=snapshot.digest,
    )
    digest = _digest({**fields, "tools": [t.model_dump(mode="json") for t in fields["tools"]]})
    return ValidationReport(**fields, digest=digest)


class CatalogScope(FrozenModel):
    identity: Identity
    capabilities: tuple[Capability, ...]
    factory_ids: tuple[ObjectId, ...]
    policy_version: str = ""


class CatalogEntry(FrozenModel):
    tenant_id: ObjectId
    service_id: ObjectId
    config_revision: int = Field(ge=1)
    generation: int = Field(ge=1)
    discovery_id: ObjectId
    alias: str
    original_name: OriginalToolName
    capability: Capability
    contract_version: Literal["1"]
    factory_ids: tuple[ObjectId, ...]


class CatalogSnapshot(FrozenModel):
    catalog_id: ObjectId
    tenant_id: ObjectId
    reader_user_id: str
    entries: tuple[CatalogEntry, ...]
    created_at: AwareDatetime


class CatalogLease(FrozenModel):
    tenant_id: ObjectId
    service_id: ObjectId
    generation: int = Field(ge=1)
    config_revision: int = Field(ge=1)
    discovery_id: ObjectId | None = None
    target_policy_version: str
    credential_generation: str


class CatalogSource(FrozenModel):
    tenant_id: ObjectId
    service_id: ObjectId
    config_revision: int = Field(ge=1)
    generation: int = Field(ge=1)
    state: str
    discovery_id: ObjectId | None = None
    validation_digest: Digest | None = None
    reader_user_ids: tuple[str, ...]
    registration_json: str
    target_policy_version: str = ""
    reader_grant_version: str = ""


def build_catalog(
    scope: CatalogScope,
    current_heads: Iterable[CatalogSource],
    validated_snapshots: Mapping[str, ValidationReport],
) -> CatalogSnapshot:
    entries, aliases, versions = [], {}, []
    for head in current_heads:
        if (
            head.tenant_id != scope.identity.tenant_id
            or scope.identity.user_id not in head.reader_user_ids
            or head.state != "enabled"
            or not scope.policy_version
            or head.target_policy_version != scope.policy_version
        ):
            continue
        report = validated_snapshots.get(head.discovery_id)
        if report is not None:
            try:
                report = ValidationReport.model_validate_json(report.model_dump_json())
            except ValueError:
                continue
        if (
            report is None
            or not report.valid
            or report.digest != head.validation_digest
            or report.schema_profile != SCHEMA_PROFILE
        ):
            continue
        registration = Registration.model_validate_json(head.registration_json)
        if registration.tenant_id != head.tenant_id or registration.service_id != head.service_id:
            continue
        if report.registration_digest != _digest(registration.model_dump(mode="json")):
            continue
        versions.append(
            (
                head.service_id,
                head.config_revision,
                head.generation,
                head.target_policy_version,
                head.reader_grant_version,
                tuple(sorted(head.reader_user_ids)),
            )
        )
        for tool in report.tools:
            if tool.capability not in scope.capabilities:
                continue
            factories = tuple(
                sorted(
                    {
                        f
                        for b in registration.bindings
                        if b.tool_name == tool.original_name and b.capability == tool.capability
                        for f in b.factory_ids
                    }
                    & set(scope.factory_ids)
                )
            )
            if not factories:
                continue
            key = (
                head.tenant_id,
                head.service_id,
                tool.original_name,
                tool.capability,
                tool.contract_version,
            )
            if tool.alias in aliases and aliases[tool.alias] != key:
                raise ValueError("source_conflict")
            aliases[tool.alias] = key
            entries.append(
                CatalogEntry(
                    tenant_id=head.tenant_id,
                    service_id=head.service_id,
                    config_revision=head.config_revision,
                    generation=head.generation,
                    discovery_id=head.discovery_id,
                    alias=tool.alias,
                    original_name=tool.original_name,
                    capability=tool.capability,
                    contract_version=tool.contract_version,
                    factory_ids=factories,
                )
            )
    entries.sort(key=lambda entry: _json(entry.model_dump(mode="json")))
    catalog_id = _digest(
        {
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "versions": sorted(versions),
            "scope": scope.model_dump(mode="json"),
        }
    )
    return CatalogSnapshot(
        catalog_id=catalog_id,
        tenant_id=scope.identity.tenant_id,
        reader_user_id=scope.identity.user_id,
        entries=tuple(entries),
        created_at=datetime.now(UTC),
    )
