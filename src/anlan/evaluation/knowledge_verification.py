"""Verify raw inputs, trace payload and causal observation rescoring, offline only."""

import json
from pathlib import Path

from .contracts import Manifest
from .knowledge_contracts import Observation, RunIndex, canonical, digest
from .knowledge_scoring import score_knowledge_observation, validate_dependencies
from .report import evaluate_bundle


def verify_knowledge_run(index_path):
    errors = []
    try:
        root = Path(index_path).resolve().parent
        index = RunIndex.model_validate_json(Path(index_path).read_bytes())
        if index.status != "complete" or index.artifact_dir != str(root):
            raise ValueError("partial or wrong root")
        if [e.case_id for e in index.cases] != index.catalog.cases:
            raise ValueError("missing/duplicate cases")

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
                raise ValueError("artifact hash mismatch")
            return raw

        manifest = json.loads(load(index.manifest))
        Manifest.model_validate(manifest)
        if manifest["required_case_ids"] != index.catalog.cases:
            raise ValueError("manifest cases mismatch")
        rows = []
        for entry in index.cases:
            inputs = json.loads(load(entry.input))
            obs = Observation.model_validate_json(load(entry.observation))
            trace = [json.loads(line) for line in load(entry.trace).splitlines()]
            if (
                trace != [e.model_dump(mode="json") for e in obs.events]
                or obs.inputs != inputs
                or obs.input_content_sha256 != digest(canonical(inputs))
                or obs.manifest_sha256 != index.manifest.sha256
                or (obs.case_id, obs.case_run_id, obs.eval_run_id)
                != (entry.case_id, entry.case_run_id, index.eval_run_id)
            ):
                raise ValueError("trace/input/run binding mismatch")
            if len(entry.sources) != len(inputs["sources"]):
                raise ValueError("missing raw source")
            for ref, source in zip(entry.sources, inputs["sources"]):
                raw = load(ref)
                if raw.hex() != source["hex"] or digest(raw) != source["sha256"]:
                    raise ValueError("raw byte mismatch")
            validate_dependencies(obs)
            rows.append(
                score_knowledge_observation(
                    obs.model_dump(mode="json"), entry.observation.model_dump()
                )
            )
        if index.bundle is None or index.report is None:
            raise ValueError("missing report")
        bundle = json.loads(load(index.bundle))
        report = json.loads(load(index.report))
        if bundle != {"manifest": manifest, "cases": rows} or evaluate_bundle(bundle) != report:
            raise ValueError("raw observation scores/report mismatch")
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        errors.append(str(exc))
    return dict(valid=not errors, errors=errors)
