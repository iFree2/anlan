"""Conservative adapter for saved materials-v1 reports; never rescore semantics."""

import hashlib
import json

from .contracts import Bundle, Manifest


def adapt_materials_v1(source: dict, manifest: dict) -> dict:
    meta = Manifest.model_validate(manifest)
    if source.get("mode") != "offline" or meta.request_attempts != 0:
        raise ValueError("materials-v1 adapter supports offline zero-request sources only")
    if source.get("dataset_version") != "materials-v1-dev-seen":
        raise ValueError("unsupported legacy dataset version")
    if not isinstance(source.get("results"), list) or not source["results"]:
        raise ValueError("legacy results must be nonempty")
    pending = {"status": "pending", "evidence": "Not measured by legacy materials-v1 report"}
    cases = []
    for row in source["results"]:
        analysis = row["state"]["analysis"]
        exact = row["scores"]["exact_match"]
        if type(exact) is not bool:
            raise ValueError("legacy exact_match must be boolean")
        usage = analysis.get("usage") or {}
        cases.append(
            {
                "case_id": row["case_id"],
                "origin": "SYNTHETIC",
                "split": "seen_regression",
                "slice": "legacy_materials_structure",
                "severity": "high",
                "structure": {
                    "status": "pending",
                    "evidence": "Legacy output schema not revalidated",
                },
                "legacy_issue_set": {
                    "status": "pass" if exact else "fail",
                    "evidence": "Legacy predicted issue set equals expected issue set",
                },
                "semantic": pending,
                "semantic_source": "not_measured",
                "human": pending,
                "human_reviewer": None,
                "safety": {},
                "errors": [str(analysis["error"])] if analysis.get("error") else [],
                "latency_ms": row.get("elapsed_ms"),
                "cost_usd": None,
                "total_tokens": usage.get("total_tokens"),
            }
        )
    payload = {
        "manifest": meta.model_dump(mode="json"),
        "cases": cases,
        "provenance": {
            "adapter": "materials-v1",
            "source_sha256": hashlib.sha256(
                json.dumps(source, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            "source_created_at": source["created_at"],
            "limitation": "Normalized JSON hash; source timestamps retained. Structure only; "
            "no inherited structure, safety, semantic or human pass. "
            "Issue-set correctness is separate. Timings are historical.",
        },
    }
    return Bundle.model_validate(payload).model_dump(mode="json")
