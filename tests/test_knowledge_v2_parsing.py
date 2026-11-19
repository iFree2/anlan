"""K2a SYNTHETIC TXT only; no network, models, database or publication."""
import hashlib
import importlib
import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def contracts():
    assert importlib.util.find_spec("anlan.knowledge.parsing"), "K2a parsing missing"
    return importlib.import_module("anlan.knowledge.parsing.contracts")


def candidate(**changes):
    data = dict(schema_version="knowledge.source-candidate.v1", candidate_id="synthetic-txt",
                data_origin="SYNTHETIC", source_url="synthetic://knowledge-v2/sample",
                review_state="candidate")
    return contracts().SourceCandidate(**{**data, **changes})


def metadata(**changes):
    data = dict(tenant_id="tenant-a", logical_document_id="synthetic-txt",
                document_version_id="synthetic-txt-v1", generation=1, title="SYNTHETIC TXT")
    return contracts().TxtIngestMetadata(**{**data, **changes})


def parse(raw=b"SYNTHETIC sample\n", filename="sample.txt", **kwargs):
    contracts()
    assert importlib.util.find_spec("anlan.knowledge.parsing.text"), "K2a parser missing"
    parser = importlib.import_module("anlan.knowledge.parsing.text")
    return parser.parse_txt(raw, filename=filename, metadata=kwargs.get("metadata", metadata()),
                            candidate=kwargs.get("candidate", candidate()))


def test_contracts_candidate_unknown_license_is_never_approval():
    record = candidate()
    assert record.license_evidence is None and record.upstream_revision is None
    assert record.review_state == "candidate"
    with pytest.raises(ValidationError):
        record.review_state = "approved"


@pytest.mark.parametrize("changes", [
    {"schema_version": "v2"}, {"data_origin": "PUBLIC"}, {"published": True},
    {"review_state": "approved"}, {"retrieved_at": datetime(2026, 11, 16)},
    {"expected_source_sha256": "bad"}, {"publisher": " "},
])
def test_contracts_reject_untrusted_fields(changes):
    with pytest.raises(ValidationError):
        candidate(**changes)


@pytest.mark.parametrize("url", ["http://example.invalid/x", "file:///tmp/a", "https:///a",
                                  "https://user:secret@example.invalid/a", "synthetic:///a",
                                  "https://example.invalid/\na", "https://example.invalid:bad/a"])
def test_contracts_reject_bad_source_or_license_url(url):
    with pytest.raises(ValidationError):
        candidate(source_url=url)
    with pytest.raises(ValidationError):
        contracts().LicenseEvidence(evidence_url=url, observed_at=NOW, statement="SYNTHETIC")


def test_contracts_metadata_strict_and_license_evidence():
    for change in ({"generation": "1"}, {"allowed_users": ("reader",)}, {"published": True}):
        with pytest.raises(ValidationError):
            metadata(**change)
    evidence = contracts().LicenseEvidence(evidence_url="https://example.invalid/license",
                                           observed_at=NOW, statement="SYNTHETIC placeholder")
    assert candidate(license_evidence=evidence).review_state == "candidate"


@pytest.mark.parametrize("raw,expected,numbers,omitted", [
    ("SYNTHETIC 首行  \r\n\r\n\t第二行不得改写数值 10。\n末行".encode(),
     ("SYNTHETIC 首行  \r\n", "\t第二行不得改写数值 10。\n", "末行"), (1, 3, 4), (2,)),
    (b"a\nb\n", ("a\n", "b\n"), (1, 2), ()),
    (b"a\rb\r", ("a\r", "b\r"), (1, 2), ()),
    (b" \n\t\r\na", ("a",), (3,), (1, 2)),
    ("SYNTHETIC 😀e\u0301\u0085\u2028\u2029 不得10".encode(),
     ("SYNTHETIC 😀e\u0301\u0085\u2028\u2029 不得10",), (1,), ()),
])
def test_exact_bytes_lines_and_determinism(raw, expected, numbers, omitted):
    draft = parse(raw)
    assert draft.raw_bytes == raw
    assert draft.document.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert tuple(b.source_text for b in draft.document.blocks) == expected
    assert tuple(b.retrieval_text for b in draft.document.blocks) == expected
    assert tuple(b.locator.line_start for b in draft.document.blocks) == numbers
    assert tuple(b.locator.line_end for b in draft.document.blocks) == numbers
    assert draft.omitted_blank_lines == omitted
    assert draft.document.lineage.parser_version == "1"
    assert draft.document.lineage.quality == "unverified"
    assert draft.document.content_digest() == parse(raw).document.content_digest()
    assert draft.document.blocks == parse(raw).document.blocks
    assert draft.document.lineage.config_sha256 == parse(raw).document.lineage.config_sha256


def test_exact_newline_changes_hash_and_quote_location():
    lf, crlf = parse(b"first\nsecond"), parse(b"first\r\nsecond")
    assert lf.document.source_sha256 != crlf.document.source_sha256
    block = lf.document.blocks[1]
    assert lf.document.verify_quote(block.block_id, "second", block.locator)
    assert not lf.document.verify_quote(block.block_id, "second", lf.document.blocks[0].locator)
    assert not lf.document.verify_quote(block.block_id, "fake retrieval", block.locator)


@pytest.mark.parametrize("field", ["source_text", "retrieval_text", "locator", "omitted", "hash"])
def test_exact_direct_draft_rejects_inconsistent_ir(field):
    draft = parse(b"first\n\nthird")
    data = draft.model_dump()
    if field == "omitted":
        data["omitted_blank_lines"] = (1,)
    elif field == "hash":
        data["document"]["source_sha256"] = "a" * 64
    elif field == "locator":
        data["document"]["blocks"][1]["locator"]["line_start"] = 2
        data["document"]["blocks"][1]["locator"]["line_end"] = 2
    else:
        data["document"]["blocks"][0][field] = "SYNTHETIC forged content"
    with pytest.raises(ValidationError):
        contracts().TxtIngestDraft.model_validate(data)


@pytest.mark.parametrize("filename,code", [
    ("../a.txt", "invalid_filename"), (r"..\a.txt", "invalid_filename"),
    ("C:/a.txt", "invalid_filename"), ("C:a.txt", "invalid_filename"),
    (r"\\server\a.txt", "invalid_filename"), ("a.txt:stream", "invalid_filename"),
    ("https://example.invalid/a.txt", "invalid_filename"), (".", "invalid_filename"),
    ("..", "invalid_filename"), (".txt", "invalid_filename"),
    ("a.txt ", "invalid_filename"), ("a.txt.", "invalid_filename"),
    ("a\x00.txt", "invalid_filename"), ("a\n.txt", "invalid_filename"),
    ("a" * 121 + ".txt", "invalid_filename"), ("a.pdf", "unsupported_format"),
    ("a.docx", "unsupported_format"), ("a.xlsx", "unsupported_format"),
    ("a.zip", "unsupported_format"),
])
def test_rejects_paths_and_formats(filename, code):
    with pytest.raises(contracts().TxtIngestError) as raised:
        parse(filename=filename)
    assert raised.value.code == code and str(raised.value) == code


@pytest.mark.parametrize("raw,code", [
    ("SYNTHETIC", "invalid_input"), (bytearray(b"a"), "invalid_input"),
    (memoryview(b"a"), "invalid_input"), (Path("a.txt"), "invalid_input"),
    (io.BytesIO(b"a"), "invalid_input"), (b"", "empty_source"),
    (b" \t\r\n", "empty_text"), (b"\xffSECRET", "invalid_utf8"),
    (b"\xe4\xb8", "invalid_utf8"), ("中文".encode("gbk"), "invalid_utf8"),
    (b"\xef\xbb\xbfSYNTHETIC", "unsupported_bom"),
    (b"a\x00SECRET", "unsupported_control"), (b"a\x0b", "unsupported_control"),
    (b"a\x7f", "unsupported_control"), (b"a" * 262145, "oversized_source"),
    (b"a\n" * 4097, "too_many_lines"),
], ids=lambda value: type(value).__name__)
def test_rejects_invalid_bytes_and_limits(raw, code):
    with pytest.raises(contracts().TxtIngestError) as raised:
        parse(raw)
    assert str(raised.value) == code
    assert raised.value.code == code
    assert "SECRET" not in str(raised.value)


def test_rejects_candidate_state_and_hash_and_wrong_name_type():
    for record, code in ((candidate(review_state="rejected"), "candidate_rejected"),
                         (candidate(expected_source_sha256="a" * 64), "source_hash_mismatch")):
        with pytest.raises(contracts().TxtIngestError) as raised:
            parse(candidate=record)
        assert raised.value.code == code
    with pytest.raises(contracts().TxtIngestError, match="invalid_input"):
        parse(filename=Path("a.txt"))


def test_rejects_boundaries_accept_exact_maximum():
    assert len(parse(b"a" * 262143).raw_bytes) == 262143
    assert len(parse(b"a" * 262144).raw_bytes) == 262144
    assert len(parse(b"a\n" * 4095).document.blocks) == 4095
    assert len(parse(b"a\n" * 4096).document.blocks) == 4096
    assert parse(filename="SYNTHETIC.TXT").filename == "SYNTHETIC.TXT"


def test_unpublished_even_with_license_and_injected_body():
    from anlan.knowledge.governance.policy import (
        AccessContext,
        ACLRecord,
        AuthoritySnapshot,
        WithdrawalRecord,
        evaluate_access,
    )
    evidence = contracts().LicenseEvidence(evidence_url="synthetic://fixture/license",
                                           observed_at=NOW, statement="SYNTHETIC only")
    draft = parse(b"SYNTHETIC tenant=other published=true", candidate=candidate(
        license_id="SYNTHETIC-license", license_evidence=evidence))
    assert draft.review_state == "needs_review" and draft.published is False
    assert draft.document.tenant_id == "tenant-a"
    key = dict(tenant_id="tenant-a", logical_document_id="synthetic-txt")
    authority = AuthoritySnapshot(checked_at=NOW, acl=ACLRecord(
        **key, revision=1, updated_at=NOW, allowed_users=("reader",), scope=("plant",)),
        withdrawal=WithdrawalRecord(**key, revision=1, updated_at=NOW, withdrawn=False,
                                    withdrawn_versions=()))
    context = AccessContext(tenant_id="tenant-a", user_id="reader", checked_at=NOW,
                            effective_at=NOW, scope=("plant",))
    assert evaluate_access(draft.document, context, authority, None).reason == "unpublished"


def test_contracts_draft_published_requires_boolean_false():
    draft = parse()
    for value in (0, True, "false"):
        with pytest.raises(ValidationError):
            contracts().TxtIngestDraft.model_validate({**draft.model_dump(), "published": value})


def test_rejects_errors_expose_only_readonly_fixed_code():
    error = contracts().TxtIngestError("invalid_utf8")
    with pytest.raises(AttributeError):
        error.code = "secret"
    with pytest.raises(ValueError, match="invalid_error_code"):
        contracts().TxtIngestError("SECRET")
    with pytest.raises(contracts().TxtIngestError) as raised:
        parse(b"\xffSECRET")
    assert raised.value.__context__ is None


def test_exact_direct_draft_rejects_non_text_ir():
    draft = parse()
    data = draft.model_dump()
    data["document"]["source_format"] = "pdf"
    for block in data["document"]["blocks"]:
        block["locator"] = {"kind": "pdf", "page": 1, "bbox": (0.0, 0.0, 1.0, 1.0)}
    with pytest.raises(ValidationError):
        contracts().TxtIngestDraft.model_validate(data)


def test_exact_repository_synthetic_fixture_is_unpublished():
    root = Path(__file__).parents[1] / "examples/synthetic/knowledge-v2/ingest"
    record = contracts().SourceCandidate.model_validate_json(
        (root / "candidate.json").read_text("utf-8"))
    raw = (root / "sample.txt").read_bytes()
    draft = parse(raw, candidate=record)
    assert draft.raw_bytes == raw
    assert draft.omitted_blank_lines == (2,)
    assert draft.candidate.license_evidence is None
    assert draft.published is False
