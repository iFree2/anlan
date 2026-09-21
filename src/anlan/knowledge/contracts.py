"""Knowledge document, query and citation contracts without storage or model adapters."""
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from anlan.common.models import StrictModel
from anlan.tools.contracts import ObjectId

Paragraph = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000)]

class KnowledgeDocument(StrictModel):
    data_origin: Literal["SYNTHETIC"]
    doc_id: ObjectId
    version: int = Field(ge=1, strict=True)
    title: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120)]
    source: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=300)]
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    allowed_users: list[ObjectId] = Field(default_factory=list, max_length=30)
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_from >= self.valid_until:
            raise ValueError("invalid document validity")
        return self

class KnowledgeQuery(StrictModel):
    question: Annotated[str, StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=500)]
    top_k: int = Field(default=3, ge=1, le=5, strict=True)
    strategy: Literal["vector", "hybrid"] = "vector"
    minimum_score: float = Field(default=0.45, ge=0, le=1)


class KnowledgeCitation(StrictModel):
    chunk_id: ObjectId
    quote: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
