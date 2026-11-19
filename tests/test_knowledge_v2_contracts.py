"""Offline K1 contract regressions; all content is synthetic."""
import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def api():
    # An assertion gives an explicit behavioral RED before the package exists.
    from anlan import knowledge
    assert importlib.util.find_spec(f"{knowledge.__name__}.documents"), "DocumentIR v2 missing"
    return importlib.import_module("anlan.knowledge.documents.contracts")


def sample():
    return json.loads((Path(__file__).parents[1] /
                       "examples/synthetic/knowledge-v2/document.json").read_text("utf-8"))


def load(data=None):
    return api().DocumentIR.model_validate_json(json.dumps(sample() if data is None else data))


def test_versioned_source_and_retrieval_are_separate():
    doc = load()
    assert doc.schema_version == "knowledge.document.v2"
    assert doc.blocks[1].source_text != doc.blocks[1].retrieval_text
    assert doc.lineage.parser_version == "fixture-1"
    assert doc.blocks[1].parent_id == "section"
    assert doc.blocks[1].dependencies == ("section",)
    with pytest.raises(ValidationError):
        doc.title = "mutated"


@pytest.mark.parametrize("change", [
    {"schema_version": "knowledge.document.v3"}, {"published": True},
    {"generation": "1"}, {"source_sha256": "bad"},
])
def test_strict_version_and_fields(change):
    data = sample()
    data.update(change)
    with pytest.raises(ValidationError):
        load(data)


@pytest.mark.parametrize("locator", [
    {"kind": "docx", "paragraph_id": "p1", "page": 2},
    {"kind": "pdf", "page": 0, "bbox": [0, 0, 10, 10]},
    {"kind": "pdf", "page": 1, "bbox": [10, 0, 0, 10]},
    {"kind": "xlsx", "sheet": "SYNTHETIC", "cell_range": "B2:A1"},
    {"kind": "text", "line_start": 3, "line_end": 1},
])
def test_reject_wrong_locations(locator):
    data = sample()
    data["blocks"][1]["locator"] = locator
    with pytest.raises(ValidationError):
        load(data)


@pytest.mark.parametrize("kind,locator", [
    ("pdf", {"kind": "pdf", "page": 1, "bbox": [0, 0, 10, 10]}),
    ("xlsx", {"kind": "xlsx", "sheet": "SYNTHETIC", "cell_range": "A1:B2"}),
    ("text", {"kind": "text", "line_start": 1, "line_end": 2}),
    ("image", {"kind": "image", "image_id": "image1", "bbox": [0, 0, 10, 10]}),
])
def test_format_locations(kind, locator):
    data = sample()
    data["source_format"] = kind
    for block in data["blocks"]:
        block["locator"] = locator
    assert load(data).source_format == kind


@pytest.mark.parametrize("mutation", ["missing_parent", "cycle", "dependency", "duplicate"])
def test_reject_broken_graph(mutation):
    data = sample()
    if mutation == "missing_parent":
        data["blocks"][1]["parent_id"] = "absent"
    elif mutation == "cycle":
        data["blocks"][0]["dependencies"] = ["clause"]
    elif mutation == "dependency":
        data["blocks"][1]["dependencies"] = ["absent"]
    else:
        data["blocks"][1]["block_id"] = "section"
    with pytest.raises(ValidationError):
        load(data)


def test_quote_requires_exact_source_and_location():
    doc = load()
    block = doc.blocks[1]
    assert doc.verify_quote("clause", "SYNTHETIC 原文", block.locator)
    assert not doc.verify_quote("clause", "检索扩展", block.locator)
    assert not doc.verify_quote("absent", "SYNTHETIC 原文", block.locator)
    assert not doc.verify_quote("clause", "", block.locator)
    assert not doc.verify_quote("clause", "SYNTHETIC 原文", doc.blocks[0].locator)


def test_table_preserves_headers_units_footnotes_and_cells():
    data = sample()
    data["blocks"][1].update(kind="table", table={
        "headers": [["SYNTHETIC 参数", "值"]], "units": ["", "mg/m3"],
        "rows": [["示例", "10"]], "footnotes": ["SYNTHETIC 仅合成示例"],
    })
    doc = load(data)
    assert doc.blocks[1].table.rows[0][1] == "10"
    assert doc.blocks[1].table.footnotes
    data["blocks"][1]["table"]["rows"] = [["missing value"]]
    with pytest.raises(ValidationError):
        load(data)


def test_table_kind_requires_table_structure():
    data = sample()
    data["blocks"][1]["kind"] = "table"
    with pytest.raises(ValidationError):
        load(data)


@pytest.mark.parametrize("quote", [" ", "\t", "\n", 1, True, None, ["SYNTHETIC"]])
def test_quote_rejects_whitespace_and_non_strings(quote):
    doc = load()
    assert doc.verify_quote("clause", quote, doc.blocks[1].locator) is False
