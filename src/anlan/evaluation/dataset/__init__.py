"""Dataset authoring API. Does not modify the E1 runtime manifest."""

from .contracts import Catalog, DatasetManifest, ValidationResult
from .manifest import build_manifest
from .validation import prompt_fingerprint, validate_catalog

__all__ = ['Catalog', 'DatasetManifest', 'ValidationResult', 'build_manifest',
           'prompt_fingerprint', 'validate_catalog']
