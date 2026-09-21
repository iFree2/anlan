"""Review candidate contracts and source validation; no provider or storage dependencies."""
import json
from typing import Literal

from pydantic import Field

from anlan.common.models import NonEmpty, StrictModel
from anlan.knowledge.contracts import KnowledgeCitation

WORK_PACKAGE = "P3-WP03"

class Claim(StrictModel):
    text: NonEmpty
    observation_ids: list[str] = Field(max_length=3)
    knowledge_citations: list[KnowledgeCitation] = Field(max_length=3)

class Presentation(StrictModel):
    detail_level: Literal["brief", "detailed"]
    presentation_order: Literal["unknowns_first", "sources_first"]

class ReviewCandidate(StrictModel):
    claims: list[Claim] = Field(min_length=1, max_length=6)
    unknown_observation_ids: list[str] = Field(max_length=3)
    presentation: Presentation
    notice: Literal["待人工复核；不是作业批准"]

def validate_candidate(candidate: ReviewCandidate, context: dict):
    data = json.loads(context["messages"][1]["content"])
    observations = {o["observation_id"]: o for o in data["observations"]}
    chunks = {c["chunk_id"]: c["quote"] for c in data["knowledge"]}
    unknown = {key for key, o in observations.items() if o["outcome"] != "ok"}
    if (set(candidate.unknown_observation_ids) != unknown
            or len(candidate.unknown_observation_ids) != len(unknown)):
        raise ValueError("Unknown observations must be preserved exactly")
    covered, cited = set(), set()
    for claim in candidate.claims:
        if not claim.observation_ids and not claim.knowledge_citations:
            raise ValueError("Each claim requires an observed source")
        if (not set(claim.observation_ids) <= observations.keys()
                or len(set(claim.observation_ids)) != len(claim.observation_ids)):
            raise ValueError("Invalid observation reference")
        covered.update(claim.observation_ids)
        for citation in claim.knowledge_citations:
            if (citation.chunk_id not in chunks or not citation.quote.strip()
                    or citation.quote not in chunks[citation.chunk_id]):
                raise ValueError("Citation is not in model-visible context")
            cited.add(citation.chunk_id)
    if covered != observations.keys() or (chunks and not cited):
        raise ValueError("Required evidence was omitted")
    return candidate
