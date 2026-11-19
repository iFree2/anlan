"""Synthetic reviewed rectangular IR, without reading a real workbook."""
import importlib
import importlib.util

import pytest

from anlan.knowledge.documents.contracts import Block, SheetLocation, Table, TextLocation
from anlan.knowledge.retrieval.contracts import CellFilter, EvidenceKey

KEY = EvidenceKey(tenant_id="t", logical_document_id="d", document_version_id="v",
                  generation=1, block_id="table")


def query(block, filters=(), row_limit=20, **kwargs):
    name = "anlan.knowledge.retrieval.tables"
    assert importlib.util.find_spec(name) is not None, "table implementation missing"
    return importlib.import_module(name).query_table_block(block, KEY, filters, row_limit, **kwargs)


def block(values=("10", "9.9"), cell_range=None):
    table = Table(headers=(("SYNTHETIC", "limit"), ("name", "value")),
                  rows=tuple((f"item{i}", value) for i, value in enumerate(values)),
                  units=("", "m"), footnotes=("Synthetic footnote",))
    return Block(block_id="table", kind="table", order=0,
                 source_text="SYNTHETIC " + " ".join(cell for row in table.rows for cell in row),
                 retrieval_text="synthetic limits", table=table,
                 locator=SheetLocation(kind="xlsx", sheet="SYNTHETIC",
                                       cell_range=cell_range or f"A1:B{len(values) + 2}"))


def flt(op="ge", value="10", expected_unit="m", column=1):
    return CellFilter(column=column, op=op, value=value, expected_unit=expected_unit)


def codes(selection):
    return tuple(issue.code for issue in selection.issues)


def test_multilevel_headers_derive_b3_preserving_literal_values():
    source = block()
    selection = query(source, (flt(),))
    assert selection.scanned_rows == 2 and not selection.issues
    assert len(selection.rows) == 1
    row = selection.rows[0]
    assert row.table_key == KEY and row.row_index == 0
    assert tuple(c.value for c in row.cells) == ("item0", "10")
    assert tuple(c.locator.cell for c in row.cells) == ("A3", "B3")
    assert row.cells[1].locator.model_dump() == {
        "schema_version": "knowledge.table-cell.v1", "sheet": "SYNTHETIC", "cell": "B3",
        "data_row": 0, "column": 1, "derivation": "derived_from_reviewed_ir"}
    assert source.table.headers == (("SYNTHETIC", "limit"), ("name", "value"))
    assert source.table.units == ("", "m") and source.table.footnotes == ("Synthetic footnote",)


@pytest.mark.parametrize("op,value,expected", [
    ("ge", "10", (0, 1)), ("gt", "10", ()), ("le", "-1", (3,)),
    ("lt", "10", (2, 3)), ("eq", "10", (0,)), ("eq", "10.0", (1,)),
])
def test_decimal_boundaries_negative_and_exact_strings(op, value, expected):
    selection = query(block(("10", "10.0", "9.9", "-1")), (flt(op, value),))
    assert tuple(r.row_index for r in selection.rows) == expected
    assert not selection.issues


@pytest.mark.parametrize("value", ["NaN", "Inf", "1e2", "1,000", "10m", "", " 10", "１２"])
def test_unknown_cell_is_observable_not_false(value):
    selection = query(block((value, "10")), (flt(),))
    assert tuple(r.row_index for r in selection.rows) == (1,)
    assert codes(selection) == ("unknown_cell_value",)


@pytest.mark.parametrize("filter_", [flt(expected_unit=None), flt(expected_unit="cm"),
                                     flt(value="NaN"), flt(column=3)])
def test_unknown_unit_filter_and_column_fail_closed(filter_):
    selection = query(block(), (filter_,))
    assert not selection.rows and codes(selection) == ("unknown_cell_value",)


def test_unknown_in_and_filter_is_reported_even_after_false_predicate():
    selection = query(block(("NaN",)), (flt("eq", "missing", column=0), flt()))
    assert not selection.rows and codes(selection) == ("unknown_cell_value",)


@pytest.mark.parametrize("cell_range", ["A1:C4", "A1:B5", "A1:B3"])
def test_dimensions_must_equal_entire_headers_plus_rows(cell_range):
    selection = query(block(cell_range=cell_range))
    assert not selection.rows and codes(selection) == ("physical_cell_location_unavailable",)


def test_non_xlsx_and_source_mismatch_do_not_invent_addresses():
    source = block()
    selection = query(source.model_copy(update={"locator": TextLocation(
        kind="text", line_start=1, line_end=5)}))
    assert codes(selection) == ("physical_cell_location_unavailable",)
    selection = query(source.model_copy(update={"source_text": "SYNTHETIC missing cells"}))
    assert not selection.rows and codes(selection) == ("data_error",)


@pytest.mark.parametrize("count,expected", [(200, ()), (201, ("table_scan_limited",))])
def test_scan_boundary_200_201_with_no_matches(count, expected):
    selection = query(block(("1",) * count), (flt(),))
    assert not selection.rows and selection.scanned_rows == 200 and codes(selection) == expected


def test_row_limit_is_observable_and_does_not_prevent_scan():
    selection = query(block(("10",) * 201), row_limit=1)
    assert len(selection.rows) == 1 and selection.scanned_rows == 200
    assert set(codes(selection)) == {"result_limited", "table_scan_limited"}


def test_offset_range_and_empty_cell_and_scan_override():
    selection = query(block(("",), cell_range="Z4:AA6"))
    assert tuple(c.locator.cell for c in selection.rows[0].cells) == ("Z6", "AA6")
    assert selection.rows[0].cells[1].value == ""
    selection = query(block(), scan_limit=1)
    assert selection.scanned_rows == 1 and codes(selection) == ("table_scan_limited",)


@pytest.mark.parametrize("kwargs", [{"row_limit": 21}, {"row_limit": True},
                                    {"scan_limit": 201}, {"scan_limit": True}])
def test_helpers_cannot_expand_hard_limits(kwargs):
    selection = query(block(), **kwargs)
    assert not selection.rows and codes(selection) == ("data_error",)
