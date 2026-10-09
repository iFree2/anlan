"""运行时校验的 DTO。身份由宿主进程提供，绝不来自模型。"""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from anlan.common.models import NonEmpty, StrictModel

FieldName = Literal[
    "work_location_description", "work_object_description",
    "work_method_description", "attachment_description",
]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)]
LABELS: dict[FieldName, str] = {
    "work_location_description": "作业位置",
    "work_object_description": "作业对象",
    "work_method_description": "作业方式",
    "attachment_description": "附件说明",
}
QUESTIONS: dict[FieldName, str] = {
    "work_location_description": "请补充作业位置，说明区域与具体作业点。",
    "work_object_description": "请补充作业对象，说明部件或对象标识。",
    "work_method_description": "请补充作业方式，说明安全作业的方式方法",
    "attachment_description": "请说明附件描述的对象及内容；尚未提供时请如实说明。",
}


class Application(StrictModel):
    work_location_description: Text = ""
    work_object_description: Text = ""
    work_method_description: Text = ""
    attachment_description: Text = ""


class Supplement(StrictModel):
    fields: dict[FieldName, Text] = Field(min_length=1, max_length=4)


class Issue(StrictModel):
    field: FieldName
    kind: Literal["missing", "ambiguous", "missing_detail", "conflict"]
    quote: Text
    reason: NonEmpty
    question: NonEmpty
    source: Literal["rule", "model"]
