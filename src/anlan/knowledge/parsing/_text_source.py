"""Bounded byte rules shared by the parser and draft validator; no I/O."""
import hashlib
import json
import re
from typing import Literal, get_args

from anlan.knowledge.documents.contracts import Block, Lineage, TextLocation

MAX_SOURCE_BYTES = 262144
MAX_PHYSICAL_LINES = 4096
ErrorCode = Literal[
    "invalid_input", "invalid_filename", "unsupported_format", "oversized_source",
    "empty_source", "candidate_rejected", "source_hash_mismatch", "unsupported_bom",
    "invalid_utf8", "unsupported_control", "too_many_lines", "empty_text",
]


class TxtIngestError(ValueError):
    """Only a fixed code is exposed; source bytes and filename never enter the message."""

    def __init__(self, code: ErrorCode):
        if code not in get_args(ErrorCode):
            raise ValueError("invalid_error_code")
        self._code = code
        super().__init__(code)

    @property
    def code(self) -> ErrorCode:
        return self._code


def source_lines(raw: bytes, filename: str, *, rejected: bool = False,
                 expected_digest: str | None = None) -> tuple[str, ...]:
    """Validate the complete input before returning exact physical lines."""
    if type(raw) is not bytes or type(filename) is not str:
        raise TxtIngestError("invalid_input")
    if (not 1 <= len(filename) <= 120 or filename in {".", ".."}
        or filename.lower() == ".txt" or filename.endswith((" ", "."))
        or any(c in "/\\:" or ord(c) < 32 or ord(c) == 127 for c in filename)):
        raise TxtIngestError("invalid_filename")
    if not filename.lower().endswith(".txt"):
        raise TxtIngestError("unsupported_format")
    if not filename[:-4].strip():
        raise TxtIngestError("invalid_filename")
    if len(raw) > MAX_SOURCE_BYTES:
        raise TxtIngestError("oversized_source")
    if not raw:
        raise TxtIngestError("empty_source")
    if rejected:
        raise TxtIngestError("candidate_rejected")
    if expected_digest is not None and hashlib.sha256(raw).hexdigest() != expected_digest:
        raise TxtIngestError("source_hash_mismatch")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise TxtIngestError("unsupported_bom")
    invalid_utf8 = False
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        invalid_utf8 = True
    # Raise outside except: decode errors include source fragments in __context__.
    if invalid_utf8:
        raise TxtIngestError("invalid_utf8")
    if any((ord(c) < 32 and c not in "\t\r\n") or ord(c) == 127 for c in text):
        raise TxtIngestError("unsupported_control")
    lines = tuple(re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$", text))
    if len(lines) > MAX_PHYSICAL_LINES:
        raise TxtIngestError("too_many_lines")
    if not any(line.strip() for line in lines):
        raise TxtIngestError("empty_text")
    return lines


def line_blocks(lines: tuple[str, ...]) -> tuple[Block, ...]:
    blocks = []
    for number, line in enumerate(lines, 1):
        if line.strip():
            digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
            blocks.append(Block(
                block_id=f"line-{number}-{digest}", kind="paragraph", order=len(blocks),
                source_text=line, retrieval_text=line,
                locator=TextLocation(kind="text", line_start=number, line_end=number),
            ))
    return tuple(blocks)


def blank_lines(lines: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(number for number, line in enumerate(lines, 1) if not line.strip())


def parser_lineage() -> Lineage:
    config = {"max_source_bytes": MAX_SOURCE_BYTES, "max_physical_lines": MAX_PHYSICAL_LINES,
              "encoding": "utf-8-strict", "bom": "reject", "newlines": "preserve-crlf-lf-cr",
              "blank_lines": "omit-block-retain-bytes-and-line-numbers"}
    encoded = json.dumps(config, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return Lineage(parser="anlan.restricted_utf8_txt", parser_version="1",
                   config_sha256=hashlib.sha256(encoded).hexdigest(),
                   transformations=(), quality="unverified")
