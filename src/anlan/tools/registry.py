"""Single source for fixed tool definitions; no authorization is inferred from text."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from anlan.common.models import Identity


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[Identity, dict], Awaitable[BaseModel]]
    clock: Callable[[], datetime]
    object_field: str | None = None

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self, definitions: Iterable[ToolDefinition]):
        self.definitions = tuple(definitions)
        names = [d.name for d in self.definitions]
        if len(names) != len(set(names)):
            raise ValueError("duplicate tool name")

    def schemas(self):
        return [d.schema() for d in self.definitions]
