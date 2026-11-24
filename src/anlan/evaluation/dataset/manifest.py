"""Answer-free version manifest for a future explicit E1 runner adapter."""

import hashlib
import json
from pathlib import Path

from .contracts import Catalog, DatasetManifest, ManifestCase
from .validation import validate_catalog


def content_digest(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def build_manifest(data: dict, *, source_root: Path) -> DatasetManifest:
    validation = validate_catalog(data, source_root=source_root)
    if not validation.valid:
        raise ValueError('dataset invalid; inspect validate_catalog errors')
    catalog = Catalog.model_validate(data)
    return DatasetManifest(
        catalog_sha256=content_digest(catalog.model_dump(mode='json')),
        cases=[ManifestCase(case_id=c.case_id, family=c.family, split=c.split,
                            case_sha256=content_digest(c.model_dump(mode='json')),
                            source_sha256=[s.sha256 for s in c.sources]) for c in catalog.cases],
        sealed_registry_entries=len(catalog.sealed_holdouts),
    )
