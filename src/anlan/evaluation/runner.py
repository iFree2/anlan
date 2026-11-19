"""Execute native offline paths and bind their observations to immutable artifacts."""

import asyncio
import json
import platform
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from anlan.common.errors import AccessDenied
from anlan.common.models import Identity
from anlan.knowledge.documents.contracts import DocumentIR
from anlan.knowledge.governance.policy import (
    AccessContext,
    ACLRecord,
    AuthoritySnapshot,
    ReleaseManifest,
    WithdrawalRecord,
    evaluate_access,
)
from anlan.llm.tool_model import PROMPT_VERSION, SYSTEM_PROMPT
from anlan.tools.contracts import AccessData, FactData
from anlan.workflows.material_analysis import OfflineAnalyzer
from anlan.workflows.material_contracts import Application
from anlan.workflows.registry import MemoryRegistry
from anlan.workflows.service import WorkflowService
from anlan.workflows.tool_loop import check_facts_agent

from .contracts import Manifest
from .offline_fixtures import (
    FIXTURE_ROOT,
    REPO_ROOT,
    RecordedModel,
    RecordedTools,
    TraceCapture,
    canonical,
    digest,
    fixture_path,
)
from .report import evaluate_bundle, write_report
from .runner_contracts import CaseObservation, Catalog, RunIndex
from .scoring import score_observation


def load_catalog(path: Path) -> Catalog:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(FIXTURE_ROOT.resolve()):
        raise ValueError("catalog outside trusted fixture root")
    return Catalog.model_validate_json(resolved.read_bytes())


def _write(path, value):
    write_report(path, value)
    return {"path": path.name, "sha256": digest(path.read_bytes())}


def _ref(root, path):
    return {"path": path.relative_to(root).as_posix(), "sha256": digest(path.read_bytes())}


def _governance_inputs(spec):
    doc = DocumentIR.model_validate_json(fixture_path("document.json").read_bytes())
    now = spec.checked_at
    context = AccessContext(
        tenant_id="tenant-a",
        user_id="reader",
        checked_at=now,
        effective_at=spec.effective_at,
        scope=("plant-a", "hot-work"),
    )
    key = {"tenant_id": "tenant-a", "logical_document_id": "synthetic-sop"}
    acl = ACLRecord(
        **key, revision=2, updated_at=now, allowed_users=("reader",), scope=("plant-a", "hot-work")
    )
    withdrawal = WithdrawalRecord(
        **key,
        revision=3,
        updated_at=now,
        withdrawn=spec.case_id.endswith("withdrawn"),
        withdrawn_versions=(),
    )
    authority = AuthoritySnapshot(
        checked_at=now,
        acl=acl,
        withdrawal=None if spec.case_id.endswith("missing-authority") else withdrawal,
    )
    release = ReleaseManifest(
        **key,
        generation=1,
        document_version_id=doc.document_version_id,
        source_sha256=doc.source_sha256,
        ir_sha256=doc.content_digest(),
        review_status="approved",
        reviewer="SYNTHETIC-policy-fixture",
        published_at=now - timedelta(days=2),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        scope=("plant-a", "hot-work"),
    )
    return doc, context, authority, release


async def run_case(spec, context):
    root, eval_run_id, manifest_sha = context
    directory = root / "cases" / spec.case_id
    directory.mkdir(parents=True, exist_ok=False)
    case_run_id = str(uuid4())
    started = perf_counter()
    counts = {"model": 0, "handler": 0, "reader": 0}
    calls, diagnostics, errors = [], {}, []
    native, exception, loop_run_id = None, None, None
    inputs = {"scenario": spec.model_dump(mode="json")}
    if spec.family == "governance":
        objects = _governance_inputs(spec)
        inputs.update(
            dict(
                zip(
                    ("document", "context", "authority", "manifest"),
                    (item.model_dump(mode="json") for item in objects),
                )
            )
        )
    else:
        inputs.update(
            {
                "materials": json.loads(fixture_path("materials.json").read_bytes()),
                "references": {
                    "worker_id": "worker-001",
                    "qualification_type": "welding",
                    "area_id": "area-001",
                },
                "actor": "other-tenant"
                if spec.case_id.endswith("cross-tenant")
                else "synthetic-owner",
            }
        )
    _write(directory / "input.json", inputs)
    with (directory / "trace.jsonl").open("x", encoding="utf-8") as stream:
        capture = TraceCapture(
            stream,
            {"case_id": spec.case_id, "case_run_id": case_run_id, "eval_run_id": eval_run_id},
        )
        capture.event("evaluation_runner", {"event": "case_started", "family": spec.family})
        try:
            if spec.family == "governance":
                before = canonical(inputs)
                calls.append({"kind": "native_api", "name": "evaluate_access"})
                native = evaluate_access(*objects).model_dump(mode="json")
                after = dict(
                    zip(
                        ("document", "context", "authority", "manifest"),
                        (item.model_dump(mode="json") for item in objects),
                    )
                )
                diagnostics["input_unchanged"] = before == canonical(
                    {"scenario": inputs["scenario"], **after}
                )
                capture.event("evaluation_runner", {"event": "governance_decision", **native})
            else:
                trace = capture.native_trace()
                owner = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")
                actor = (
                    Identity(tenant_id="other", user_id="other")
                    if spec.case_id.endswith("cross-tenant")
                    else owner
                )
                service = WorkflowService(OfflineAnalyzer(), trace, registry=MemoryRegistry())
                baseline = await service.start(owner, inputs["materials"])
                history = await service.history(owner, baseline["task_id"])
                model = RecordedModel(spec.case_id, counts, calls)
                tools = RecordedTools(
                    spec.effective_at, spec.case_id.endswith("tool-error"), counts, calls
                )
                calls.append({"kind": "native_api", "name": "check_facts_agent"})
                try:
                    native = await check_facts_agent(
                        service,
                        actor,
                        baseline["task_id"],
                        inputs["references"],
                        tools,
                        model,
                        trace,
                    )
                    loop_run_id = native["run_id"]
                except AccessDenied:
                    exception = "AccessDenied"
                    capture.event("evaluation_runner", {"event": "native_access_denied"})
                after = await service.get(owner, baseline["task_id"])
                after_history = await service.history(owner, baseline["task_id"])
                diagnostics["state_unchanged"] = canonical(baseline) == canonical(after)
                diagnostics["history_unchanged"] = canonical(history) == canonical(after_history)
                diagnostics["binding_consistent"] = native is None or all(
                    (
                        native["source_run_id"] == baseline["run_id"],
                        native["task_id"] == baseline["task_id"],
                        native["revision"] == baseline["revision"],
                        native["correlation_id"] == baseline["correlation_id"],
                    )
                )
                calls.append(
                    {
                        "kind": "state_integrity",
                        "source_run_id": baseline["run_id"],
                        "task_id": baseline["task_id"],
                        "correlation_id": baseline["correlation_id"],
                        "revision": baseline["revision"],
                        "before_sha256": digest(canonical(baseline)),
                        "after_sha256": digest(canonical(after)),
                        "history_before": len(history),
                        "history_after": len(after_history),
                    }
                )
                if native and native.get("trace_warning"):
                    errors.append(native["trace_warning"])
        except asyncio.CancelledError:
            capture.event("evaluation_runner", {"event": "case_cancelled"})
            raise
        except Exception as exc:
            exception = type(exc).__name__
            errors.append(f"native_exception:{exception}")
        capture.event(
            "evaluation_runner",
            {"event": "case_finished", "loop_run_id": loop_run_id, "exception": exception},
        )
    observation = CaseObservation.model_validate(
        {
            "schema_version": "enterprise-observation-v1",
            "eval_run_id": eval_run_id,
            "case_run_id": case_run_id,
            "case_id": spec.case_id,
            "family": spec.family,
            "manifest_sha256": manifest_sha,
            "input_sha256": digest((directory / "input.json").read_bytes()),
            "input_content_sha256": digest(canonical(inputs)),
            "inputs": inputs,
            "loop_run_id": loop_run_id,
            "native": native,
            "exception": exception,
            "counts": counts,
            "calls": calls,
            "diagnostics": diagnostics,
            "runner_errors": errors,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        }
    ).model_dump(mode="json")
    _write(directory / "observation.json", observation)
    return observation, {
        "case_id": spec.case_id,
        "case_run_id": case_run_id,
        "family": spec.family,
        "status": "error" if errors else "complete",
        **{
            name: _ref(root, directory / filename)
            for name, filename in (
                ("input", "input.json"),
                ("observation", "observation.json"),
                ("trace", "trace.jsonl"),
            )
        },
    }


def _versions():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()

    paths = [
        *sorted((REPO_ROOT / "src/anlan/evaluation").glob("*.py")),
        *(
            REPO_ROOT / name
            for name in (
                "src/anlan/workflows/tool_loop.py",
                "src/anlan/workflows/service.py",
                "src/anlan/llm/tool_model.py",
                "src/anlan/tools/executor.py",
                "src/anlan/tools/policy.py",
                "src/anlan/tools/registry.py",
                "src/anlan/tools/builtin.py",
                "src/anlan/tools/queries.py",
                "src/anlan/knowledge/governance/policy.py",
                "src/anlan/knowledge/documents/contracts.py",
                "evals/evaluate_enterprise.py",
            )
        ),
    ]
    return {
        "code_head": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "file_hashes": {
            path.relative_to(REPO_ROOT).as_posix(): digest(path.read_bytes()) for path in paths
        },
        "prompt_sha256": digest(SYSTEM_PROMPT.encode()),
        "lock_sha256": digest((REPO_ROOT / "uv.lock").read_bytes()),
        "fixture_hashes": {
            p.relative_to(FIXTURE_ROOT).as_posix(): digest(
                fixture_path(p.relative_to(FIXTURE_ROOT).as_posix()).read_bytes()
            )
            for p in FIXTURE_ROOT.rglob("*.json")
        },
        "scorer_rule_version": "e2a-observation-scorer-v1",
    }


async def run_suite(catalog_path: Path, artifacts_dir: Path) -> dict:
    catalog = load_catalog(catalog_path)
    # Validate all fixtures before creating output directories or executing any native path.
    Application.model_validate_json(fixture_path("materials.json").read_bytes())
    AccessData.model_validate_json(fixture_path("facts/access.json").read_bytes())
    for name in ("areas.json", "qualifications.json"):
        FactData.model_validate_json(fixture_path("facts/" + name).read_bytes())
    for spec in catalog.cases:
        if spec.family == "governance":
            _governance_inputs(spec)
    versions = _versions()
    eval_run_id = str(uuid4())
    root = Path(artifacts_dir).resolve() / eval_run_id
    # Never permit execution artifacts to become mutable inputs or overwrite old evidence.
    if root.is_relative_to(FIXTURE_ROOT.resolve()):
        raise ValueError("artifacts must be outside trusted fixture root")
    root.mkdir(parents=True, exist_ok=False)
    manifest = Manifest.model_validate(
        {
            "schema_version": "enterprise-eval-v2",
            "code_version": versions["code_head"] + "+dirty"
            if versions["dirty"]
            else versions["code_head"],
            "prompt_version": PROMPT_VERSION,
            "model_version": "scripted_double:runner-v1:no-provider",
            "knowledge_version": "SYNTHETIC-K1-runner-v1",
            "dataset_version": "runner-v1-seen",
            "scorer_version": "enterprise-scorer-v2.0",
            "environment": f"local Python {platform.python_version()}",
            "run_at": datetime.now(UTC),
            "fixed_at": None,
            "request_limit": 0,
            "request_attempts": 0,
            "required_case_ids": [spec.case_id for spec in catalog.cases],
        }
    ).model_dump(mode="json")
    manifest_ref = _write(root / "manifest.json", manifest)
    index = {
        "schema_version": "enterprise-run-index-v1",
        "eval_run_id": eval_run_id,
        "artifact_dir": str(root),
        "status": "partial",
        "catalog": catalog.model_dump(mode="json"),
        "suite_sha256": digest(Path(catalog_path).read_bytes()),
        "versions": versions,
        "manifest": manifest_ref,
        "bundle": None,
        "report": None,
        "cases": [],
    }
    rows = []
    try:
        for spec in catalog.cases:
            observation, entry = await run_case(spec, (root, eval_run_id, manifest_ref["sha256"]))
            index["cases"].append(entry)
            rows.append(score_observation(spec, observation, entry["observation"]))
        bundle = {"manifest": manifest, "cases": rows}
        index["bundle"] = _write(root / "bundle.json", bundle)
        index["report"] = _write(root / "report.json", evaluate_bundle(bundle))
        index["status"] = "complete"
    finally:
        _write(root / "run-index.json", RunIndex.model_validate(index).model_dump(mode="json"))
    verification = verify_run(root / "run-index.json")
    if not verification["valid"]:
        raise ValueError("run integrity verification failed: " + str(verification["errors"]))
    return index


def verify_run(index_path: Path) -> dict:
    root = Path(index_path).resolve().parent
    errors = []
    try:
        index = RunIndex.model_validate_json(Path(index_path).read_bytes())
        if index.artifact_dir != str(root):
            raise ValueError("artifact directory binding mismatch")
        if index.status != "complete":
            raise ValueError("partial run")
        if {entry.case_id for entry in index.cases} != {
            spec.case_id for spec in index.catalog.cases
        }:
            raise ValueError("missing case observations")

        def load(ref):
            path = (root / ref.path).resolve()
            if (
                Path(ref.path).is_absolute()
                or ".." in Path(ref.path).parts
                or not path.is_relative_to(root)
            ):
                raise ValueError("artifact path escape")
            raw = path.read_bytes()
            if digest(raw) != ref.sha256:
                raise ValueError("artifact hash mismatch: " + ref.path)
            return raw

        manifest = json.loads(load(index.manifest))
        Manifest.model_validate(manifest)
        if set(manifest["required_case_ids"]) != {s.case_id for s in index.catalog.cases}:
            raise ValueError("manifest/catalog case mismatch")
        expected_rows = []
        for entry in index.cases:
            inputs = load(entry.input)
            observation = CaseObservation.model_validate_json(load(entry.observation))
            traces = [json.loads(line) for line in load(entry.trace).splitlines()]
            if not traces:
                raise ValueError("empty trace")
            if any(
                (record.get("case_id"), record.get("case_run_id"), record.get("eval_run_id"))
                != (entry.case_id, entry.case_run_id, index.eval_run_id)
                for record in traces
            ):
                raise ValueError("trace binding mismatch")
            if (
                (observation.case_id, observation.case_run_id, observation.eval_run_id)
                != (entry.case_id, entry.case_run_id, index.eval_run_id)
                or observation.manifest_sha256 != index.manifest.sha256
                or observation.input_sha256 != digest(inputs)
                or observation.input_content_sha256 != digest(canonical(json.loads(inputs)))
                or canonical(observation.inputs) != canonical(json.loads(inputs))
            ):
                raise ValueError("observation binding mismatch")
            from .runner_verification import verify_trace

            verify_trace(observation, traces)
            spec = next(s for s in index.catalog.cases if s.case_id == entry.case_id)
            expected_rows.append(
                score_observation(
                    spec, observation.model_dump(mode="json"), entry.observation.model_dump()
                )
            )
        if index.bundle is None or index.report is None:
            raise ValueError("missing bundle/report")
        bundle = json.loads(load(index.bundle))
        report = json.loads(load(index.report))
        if bundle["manifest"] != manifest or evaluate_bundle(bundle) != report:
            raise ValueError("report cannot be reproduced")
        if bundle["cases"] != expected_rows:
            raise ValueError("saved scores differ from raw observation rescoring")
        for row in bundle["cases"]:
            entry = next(entry for entry in index.cases if entry.case_id == row["case_id"])
            for check in [row["structure"], row["semantic"], row["human"], *row["safety"].values()]:
                evidence = json.loads(check["evidence"])
                if (
                    evidence["case_run_id"] != entry.case_run_id
                    or evidence["path"] != entry.observation.path
                    or evidence["sha256"] != entry.observation.sha256
                ):
                    raise ValueError("score evidence binding mismatch")
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}
