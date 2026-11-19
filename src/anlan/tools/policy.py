"""Host-only task grants, frozen before the model sees a catalog."""

import json
import re
from dataclasses import dataclass

from anlan.common.models import Identity
from anlan.knowledge.tool import KnowledgeParameters
from anlan.tools.contracts import FactReferences
from anlan.tools.registry import ToolDefinition, ToolRegistry


@dataclass(frozen=True)
class FrozenTaskGrant:
    """Host-owned authority; never construct this from a model/tool response."""

    identity: Identity
    grants: tuple[tuple[str, str], ...]

    def __post_init__(self):
        object.__setattr__(self, "identity", Identity.model_validate(self.identity.model_dump()))
        object.__setattr__(self, "grants", tuple(tuple(item) for item in self.grants))


@dataclass(frozen=True)
class TaskCatalog:
    identity: Identity
    definitions: tuple[ToolDefinition, ...]
    grants: tuple[tuple[str, str], ...]

    def schemas(self):
        return [d.schema() for d in self.definitions]

    def expected(self, name):
        return json.loads(dict(self.grants)[name])


class ToolPolicy:
    def bind_task_grant(
        self, registry: ToolRegistry, identity: Identity, grant: FrozenTaskGrant
    ) -> TaskCatalog:
        if not isinstance(grant, FrozenTaskGrant) or grant.identity != identity:
            raise ValueError("access_denied")
        definitions = {d.name: d for d in registry.definitions}
        names, canonical = set(), []

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("invalid_task_grant")
                result[key] = value
            return result

        for item in grant.grants:
            if len(item) != 2:
                raise ValueError("invalid_task_grant")
            name, encoded = item
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name)
                or name in names
                or name not in definitions
                or not isinstance(encoded, str)
            ):
                raise ValueError("invalid_task_grant")
            names.add(name)
            try:
                raw = json.loads(encoded, object_pairs_hook=unique_object)
                parsed = definitions[name].input_model.model_validate_json(encoded)
                normalized = parsed.model_dump(mode="json")
                if not isinstance(raw, dict) or raw != normalized:
                    raise ValueError("invalid_task_grant")
                if {"tenant_id", "user_id", "identity"} & raw.keys():
                    raise ValueError("invalid_task_grant")
                frozen = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False)
            except (ValueError, TypeError, RecursionError) as exc:
                raise ValueError("invalid_task_grant") from exc
            canonical.append((name, frozen))
        if names != set(definitions) or not names:
            raise ValueError("invalid_task_grant")
        return TaskCatalog(Identity.model_validate(identity.model_dump()),
                           tuple(registry.definitions), tuple(canonical))

    def snapshot(
        self,
        registry: ToolRegistry,
        identity: Identity,
        references: FactReferences,
        knowledge_question: str | None = None,
    ) -> TaskCatalog:
        refs = FactReferences.model_validate(references.model_dump())
        expected = {
            "query_worker_qualification": {
                "worker_id": refs.worker_id,
                "qualification_type": refs.qualification_type,
            },
            "query_area_status": {"area_id": refs.area_id},
        }
        if knowledge_question is not None:
            expected["query_knowledge"] = KnowledgeParameters(
                question=knowledge_question
            ).model_dump()
        definitions = tuple(d for d in registry.definitions if d.name in expected)
        return TaskCatalog(
            identity.model_copy(deep=True),
            definitions,
            tuple((d.name, json.dumps(expected[d.name])) for d in definitions),
        )
