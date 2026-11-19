"""Strict independent knowledge evaluation records, no changes to frozen E2."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Count, Measurement, Text

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "evals/enterprise-eval-v2/knowledge-runner-v1"
IDS = ("k3e-normal", "k3e-withdrawal", "k3e-table")


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture_path(relative):
    path = Path(relative)
    resolved = (FIXTURES / path).resolve()
    if path.is_absolute() or ".." in path.parts or not resolved.is_relative_to(FIXTURES.resolve()):
        raise ValueError("path outside trusted root")
    return resolved


class Catalog(Contract):
    schema_version: Literal["knowledge-evaluation-cases-v1"]
    origin: Literal["SYNTHETIC"]
    split: Literal["seen_regression"]
    cases: list[Literal["k3e-normal", "k3e-withdrawal", "k3e-table"]]

    @model_validator(mode="after")
    def all_cases(self):
        if len(set(self.cases)) != len(self.cases):
            raise ValueError("duplicate cases")
        if set(self.cases) != set(IDS):
            raise ValueError("all three frozen cases required")
        return self


class Event(Contract):
    producer: Literal["evaluation_knowledge_runner"]
    request_id: Text | None
    seq: Count
    eval_run_id: Text
    case_run_id: Text
    case_id: Text
    kind: Literal[
        "case_started",
        "case_finished",
        "parse_started",
        "parse_finished",
        "api_started",
        "api_finished",
        "ledger_read",
        "provider_started",
        "provider_finished",
        "authority_mutation",
        "resolver_started",
        "resolver_finished",
    ]
    data: dict


class Observation(Contract):
    schema_version: Literal["knowledge-evaluation-observation-v1"]
    eval_run_id: Text
    case_run_id: Text
    case_id: Literal["k3e-normal", "k3e-withdrawal", "k3e-table"]
    manifest_sha256: Text
    input_content_sha256: Text
    inputs: dict
    drafts: list[dict]
    documents: list[dict]
    calls: list[dict]
    events: list[Event]
    diagnostics: dict[str, bool]
    errors: list[Text]
    elapsed_ms: Measurement


class FileRef(Contract):
    path: Text
    sha256: Text = Field(pattern=r"^[a-f0-9]{64}$")


class Entry(Contract):
    case_id: Text
    case_run_id: Text
    input: FileRef
    observation: FileRef
    trace: FileRef
    sources: list[FileRef]


class Versions(Contract):
    head: Text
    dirty: bool
    file_hashes: dict[str, Text]
    fixture_hashes: dict[str, Text]
    lock_sha256: Text
    python: Text
    scorer: Literal["knowledge-observation-scorer-v1"]


class RunIndex(Contract):
    schema_version: Literal["knowledge-evaluation-index-v1"]
    eval_run_id: Text
    artifact_dir: Text
    status: Literal["complete", "partial"]
    catalog: Catalog
    versions: Versions
    manifest: FileRef
    cases: list[Entry]
    bundle: FileRef | None
    report: FileRef | None
