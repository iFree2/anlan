"""Fixed adapters preserve their original typed results and underlying ACLs."""

from datetime import UTC, datetime
from types import SimpleNamespace

from anlan.knowledge.tool import KnowledgeObservation, KnowledgeParameters, query_knowledge
from anlan.tools.contracts import AreaQuery, ToolResult, WorkerQuery
from anlan.tools.registry import ToolDefinition, ToolRegistry

FIXED_SPECS = (
    (
        "query_worker_qualification",
        "读取合成人员的指定资质，返回来源时效或未知错误",
        WorkerQuery,
        "worker_id",
    ),
    ("query_area_status", "读取合成区域状态，返回来源时效或未知错误", AreaQuery, "area_id"),
)
KNOWLEDGE_DESCRIPTION = "查询授权范围内有效示例知识，只读并返回引用"


def builtin_registry(tools, knowledge_store=None):
    clock = getattr(tools, "clock", None)
    if clock is None:
        clock = (lambda: tools.now) if hasattr(tools, "now") else lambda: datetime.now(UTC)
    definitions = [
        ToolDefinition(name, description, schema, ToolResult, getattr(tools, name), clock, field)
        for name, description, schema, field in FIXED_SPECS
    ]
    if knowledge_store is not None:
        knowledge_clock = getattr(knowledge_store, "clock", clock)
        adapter = SimpleNamespace(clock=knowledge_clock, search=knowledge_store.search)

        async def knowledge(actor, parameters):
            return await query_knowledge(adapter, actor, parameters)

        definitions.append(
            ToolDefinition(
                "query_knowledge",
                KNOWLEDGE_DESCRIPTION,
                KnowledgeParameters,
                KnowledgeObservation,
                knowledge,
                getattr(knowledge_store, "clock", clock),
            )
        )
    return ToolRegistry(definitions)


def builtin_schemas(include_knowledge=False):
    specs = [(name, description, schema) for name, description, schema, _ in FIXED_SPECS]
    if include_knowledge:
        specs.append(("query_knowledge", KNOWLEDGE_DESCRIPTION, KnowledgeParameters))
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema.model_json_schema(),
            },
        }
        for name, description, schema in specs
    ]
