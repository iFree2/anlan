"""Immutable K1 IR. Validation proves structure, never source authenticity or semantics."""
import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BoxLocation(Contract):
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def ordered_box(self):
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 < float("inf") and 0 <= y0 < y1 < float("inf")):
            raise ValueError("invalid source bounding box")
        return self


class PDFLocation(BoxLocation):
    kind: Literal["pdf"]
    page: int = Field(ge=1)


class ImageLocation(BoxLocation):
    kind: Literal["image"]
    image_id: Text


class DocxLocation(Contract):
    kind: Literal["docx"]
    paragraph_id: Text
    xml_anchor: Text | None = None


class SheetLocation(Contract):
    kind: Literal["xlsx"]
    sheet: Text
    cell_range: Text

    @model_validator(mode="after")
    def ordered_cells(self):
        match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)",
                             self.cell_range)
        if not match:
            raise ValueError("invalid cell range")
        a, r0, b, r1 = match.groups()

        def column(s):
            result = 0
            for letter in s:
                result = result * 26 + ord(letter) - ord("A") + 1
            return result

        if not (column(a) <= column(b) <= 16384 and int(r0) <= int(r1) <= 1048576):
            raise ValueError("invalid cell range bounds")
        return self


class TextLocation(Contract):
    kind: Literal["text"]
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered_lines(self):
        if self.line_start > self.line_end:
            raise ValueError("invalid line range")
        return self


Location = Annotated[
    PDFLocation | ImageLocation | DocxLocation | SheetLocation | TextLocation,
    Field(discriminator="kind"),
]


class Lineage(Contract):
    parser: Text
    parser_version: Text
    config_sha256: Digest
    transformations: tuple[Text, ...] = ()
    quality: Literal["unverified", "human_verified"] = "unverified"


class Table(Contract):
    headers: tuple[tuple[str, ...], ...] = Field(min_length=1)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1)
    units: tuple[str, ...]
    footnotes: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def rectangular(self):
        width = len(self.headers[0])
        if not width or len(self.units) != width or any(
            len(row) != width for row in (*self.headers, *self.rows)
        ):
            raise ValueError("table headers, units and rows must align")
        return self


class Block(Contract):
    block_id: Text
    kind: Literal["heading", "paragraph", "list", "table", "figure", "footnote"]
    order: int = Field(ge=0)
    parent_id: Text | None = None
    dependencies: tuple[Text, ...] = ()
    source_text: Text
    retrieval_text: Text
    locator: Location
    table: Table | None = None

    @model_validator(mode="after")
    def table_shape(self):
        if (self.kind == "table") != (self.table is not None):
            raise ValueError("table structure required only for table blocks")
        return self


class DocumentIR(Contract):
    schema_version: Literal["knowledge.document.v2"]
    data_origin: Literal["SYNTHETIC"]
    tenant_id: Text
    logical_document_id: Text
    document_version_id: Text
    generation: int = Field(ge=1)
    title: Text
    source_uri: Text
    source_format: Literal["pdf", "docx", "xlsx", "text", "image"]
    source_sha256: Digest
    lineage: Lineage
    blocks: tuple[Block, ...] = Field(min_length=1)

    def content_digest(self) -> str:
        """Hash the complete validated IR with sorted UTF-8 JSON, including defaults.

        Publication binds this digest after review. This is content binding, not
        authentication of either the source asset or the publisher.
        """
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True,
                               ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def valid_graph(self):
        nodes = {block.block_id: block for block in self.blocks}
        if len(nodes) != len(self.blocks):
            raise ValueError("duplicate block identity")
        if len({b.order for b in self.blocks}) != len(self.blocks):
            raise ValueError("duplicate block order")
        edges = {}
        for block in self.blocks:
            if block.locator.kind != self.source_format:
                raise ValueError("locator does not match source format")
            refs = (*block.dependencies, *((block.parent_id,) if block.parent_id else ()))
            if any(ref not in nodes for ref in refs):
                raise ValueError("missing parent or dependency")
            edges[block.block_id] = refs
        # Iterative traversal avoids recursion limits on deeply nested source documents.
        done = set()
        for start in nodes:
            stack = [(start, False)]
            active = set()
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    active.remove(node)
                    done.add(node)
                elif node not in done:
                    if node in active:
                        raise ValueError("cyclic parent/dependency graph")
                    active.add(node)
                    stack.append((node, True))
                    stack.extend((ref, False) for ref in edges[node])
        return self

    def verify_quote(self, block_id: str, quote: str, locator: Location) -> bool:
        """Verify contiguous transcription at this locator, not semantic support."""
        return isinstance(quote, str) and bool(quote.strip()) and any(
            block.block_id == block_id and block.locator == locator and quote in block.source_text
            for block in self.blocks
        )
