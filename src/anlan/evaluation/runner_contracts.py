"""Strict local-run sidecars; E1 Manifest remains unchanged."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from .contracts import Contract, Count, Measurement, Text

CASE_IDS = (
    "e2a-fact-normal",
    "e2a-fact-outside-ref",
    "e2a-fact-cross-tenant",
    "e2a-fact-tool-error",
    "e2a-fact-bad-citation",
    "e2a-knowledge-current",
    "e2a-knowledge-withdrawn",
    "e2a-knowledge-missing-authority",
)
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ScenarioSpec(Contract):
    case_id: Text
    family: Literal["fact_loop", "governance"]
    slice: Text
    severity: Literal["critical", "high"]
    effective_at: AwareDatetime
    checked_at: AwareDatetime

    @model_validator(mode="after")
    def frozen_scenario(self):
        if self.case_id not in CASE_IDS:
            raise ValueError("unknown frozen scenario")
        expected = "fact_loop" if self.case_id.startswith("e2a-fact-") else "governance"
        if self.family != expected:
            raise ValueError("scenario family mismatch")
        return self


class Catalog(Contract):
    schema_version: Literal["enterprise-runner-cases-v1"]
    origin: Literal["SYNTHETIC"]
    split: Literal["seen_regression"]
    cases: Annotated[list[ScenarioSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def exact_catalog(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case IDs")
        if set(ids) != set(CASE_IDS):
            raise ValueError("frozen suite requires all eight scenarios")
        return self


class Counts(Contract):
    model: Count
    handler: Count
    reader: Count


class CaseObservation(Contract):
    schema_version: Literal["enterprise-observation-v1"]
    eval_run_id: Text
    case_run_id: Text
    case_id: Text
    family: Literal["fact_loop", "governance"]
    manifest_sha256: Digest
    input_sha256: Digest
    input_content_sha256: Digest
    inputs: dict
    loop_run_id: Text | None
    native: dict | None
    exception: Text | None
    counts: Counts
    calls: list[dict]
    diagnostics: dict[str, bool]
    runner_errors: list[Text]
    elapsed_ms: Measurement


class FileRef(Contract):
    path: Text
    sha256: Digest


class CaseEntry(Contract):
    case_id: Text
    case_run_id: Text
    family: Literal["fact_loop", "governance"]
    status: Literal["complete", "error"]
    input: FileRef
    observation: FileRef
    trace: FileRef


class Versions(Contract):
    code_head: Text
    dirty: bool
    file_hashes: dict[str, Digest]
    prompt_sha256: Digest
    lock_sha256: Digest
    fixture_hashes: dict[str, Digest]
    scorer_rule_version: Literal["e2a-observation-scorer-v1"]


class RunIndex(Contract):
    schema_version: Literal["enterprise-run-index-v1"]
    eval_run_id: Text
    artifact_dir: Text
    status: Literal["complete", "partial"]
    catalog: Catalog
    suite_sha256: Digest
    versions: Versions
    manifest: FileRef
    bundle: FileRef | None
    report: FileRef | None
    cases: list[CaseEntry]

    @model_validator(mode="after")
    def unique_cases(self):
        if len({row.case_id for row in self.cases}) != len(self.cases):
            raise ValueError("duplicate observation case IDs")
        return self
