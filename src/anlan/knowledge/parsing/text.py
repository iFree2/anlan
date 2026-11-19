"""Turn bounded SYNTHETIC bytes into an unreviewed IR draft without any I/O."""
import hashlib

from anlan.knowledge.documents.contracts import DocumentIR
from anlan.knowledge.parsing._text_source import (
    TxtIngestError,
    blank_lines,
    line_blocks,
    parser_lineage,
    source_lines,
)
from anlan.knowledge.parsing.contracts import (
    SourceCandidate,
    TxtIngestDraft,
    TxtIngestMetadata,
)


def parse_txt(raw: bytes, *, filename: str, metadata: TxtIngestMetadata,
              candidate: SourceCandidate) -> TxtIngestDraft:
    if not isinstance(metadata, TxtIngestMetadata) or not isinstance(candidate, SourceCandidate):
        raise TxtIngestError("invalid_input")
    lines = source_lines(raw, filename, rejected=candidate.review_state == "rejected",
                         expected_digest=candidate.expected_source_sha256)
    digest = hashlib.sha256(raw).hexdigest()
    document = DocumentIR(
        schema_version="knowledge.document.v2", data_origin="SYNTHETIC",
        **metadata.model_dump(), source_uri=f"synthetic://knowledge-v2/txt/{digest}",
        source_format="text", source_sha256=digest, lineage=parser_lineage(),
        blocks=line_blocks(lines),
    )
    return TxtIngestDraft(schema_version="knowledge.txt-draft.v1", raw_bytes=raw,
                          filename=filename, candidate=candidate, document=document,
                          omitted_blank_lines=blank_lines(lines), review_state="needs_review",
                          published=False)
