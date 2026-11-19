"""Bounded filtering of reviewed IR; addresses are derived, not XLSX-verified."""

import operator
import re
from decimal import Decimal

from anlan.knowledge.documents.contracts import Block
from anlan.knowledge.retrieval.contracts import (
    CellFilter,
    CellLocation,
    EvidenceIssue,
    EvidenceKey,
    EvidenceTableRow,
    TableCell,
    TableSelection,
)

_NUMBER = re.compile(r"[-+]?[0-9]+(?:\.[0-9]+)?")
_RANGE = re.compile(r"([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)")
_OPS = {"gt": operator.gt, "ge": operator.ge, "lt": operator.lt, "le": operator.le}


def _column_number(letters: str) -> int:
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def _column_letters(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def query_table_block(
    block: Block,
    key: EvidenceKey,
    filters: tuple[CellFilter, ...],
    row_limit: int,
    scan_limit: int = 200,
) -> TableSelection:
    """Select raw rows with fixed issues; empty complete results mean only no match.

    The caller must retain the complete table evidence (headers, units, footnotes,
    source text and digest) alongside these rows. Transcription matching here does
    not authenticate a workbook or prove physical source accuracy.
    """

    def failure(code):
        return TableSelection(issues=(EvidenceIssue(code=code, related_key=key),))

    if (
        type(row_limit) is not int
        or not 1 <= row_limit <= 20
        or type(scan_limit) is not int
        or not 1 <= scan_limit <= 200
        or key.block_id != block.block_id
    ):
        return failure("data_error")
    table = block.table
    if block.kind != "table" or table is None or block.locator.kind != "xlsx":
        return failure("physical_cell_location_unavailable")
    match = _RANGE.fullmatch(block.locator.cell_range)
    if match is None:
        return failure("physical_cell_location_unavailable")
    col0, row0, col1, row1 = match.groups()
    start_col, end_col = _column_number(col0), _column_number(col1)
    start_row, end_row = int(row0), int(row1)
    if end_col - start_col + 1 != len(table.units) or end_row - start_row + 1 != len(
        table.headers
    ) + len(table.rows):
        return failure("physical_cell_location_unavailable")
    for condition in filters:
        if condition.column >= len(table.units) or (
            condition.op != "eq"
            and (
                condition.expected_unit is None
                or condition.expected_unit != table.units[condition.column]
                or not _NUMBER.fullmatch(condition.value)
            )
        ):
            return failure("unknown_cell_value")

    rows = []
    issue_codes = []
    scanned = 0
    for index, row in enumerate(table.rows[:scan_limit]):
        scanned += 1
        if any(value and value not in block.source_text for value in row):
            # No output survives a detected source/structure mismatch.
            return TableSelection(
                scanned_rows=scanned, issues=(EvidenceIssue(code="data_error", related_key=key),)
            )
        matches, unknown = True, False
        for condition in filters:
            value = row[condition.column]
            if condition.op == "eq":
                matches = matches and value == condition.value
            elif not _NUMBER.fullmatch(value):
                unknown = True
            else:
                comparison = _OPS[condition.op](Decimal(value), Decimal(condition.value))
                matches = matches and comparison
        if unknown:
            if "unknown_cell_value" not in issue_codes:
                issue_codes.append("unknown_cell_value")
            continue
        if not matches:
            continue
        if len(rows) >= row_limit:
            if "result_limited" not in issue_codes:
                issue_codes.append("result_limited")
            continue
        cells = tuple(
            TableCell(
                value=value,
                locator=CellLocation(
                    sheet=block.locator.sheet,
                    cell=(
                        f"{_column_letters(start_col + column)}"
                        f"{start_row + len(table.headers) + index}"
                    ),
                    data_row=index,
                    column=column,
                ),
            )
            for column, value in enumerate(row)
        )
        rows.append(EvidenceTableRow(table_key=key, row_index=index, cells=cells))
    if len(table.rows) > scan_limit:
        issue_codes.append("table_scan_limited")
    return TableSelection(
        rows=tuple(rows),
        scanned_rows=scanned,
        issues=tuple(EvidenceIssue(code=code, related_key=key) for code in issue_codes),
    )
