"""Bounded immutable source catalog; projection availability is a separate concern."""

import hashlib
from dataclasses import dataclass

from anlan.knowledge.documents.contracts import DocumentIR
from anlan.knowledge.retrieval.contracts import EvidenceKey


@dataclass(frozen=True, init=False)
class InMemoryCatalog:
    documents: tuple[DocumentIR, ...]
    revision: str

    def __init__(self, documents: tuple[DocumentIR, ...]):
        if type(documents) is not tuple or len(documents) > 32:
            raise ValueError("catalog_limit")
        checked = tuple(DocumentIR.model_validate_json(d.model_dump_json()) for d in documents)
        keys = [
            (d.tenant_id, d.logical_document_id, d.document_version_id, d.generation)
            for d in checked
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate_document")
        if (
            sum(len(d.blocks) for d in checked) > 8192
            or sum(len(d.model_dump_json().encode()) for d in checked) > 8 * 1024 * 1024
        ):
            raise ValueError("catalog_limit")
        ordered = tuple(d for _, d in sorted(zip(keys, checked), key=lambda pair: pair[0]))
        revision = hashlib.sha256(
            "\n".join(d.content_digest() for d in ordered).encode()
        ).hexdigest()
        object.__setattr__(self, "documents", ordered)
        object.__setattr__(self, "revision", revision)

    def lookup(self, key: EvidenceKey):
        for doc in self.documents:
            if (
                doc.tenant_id,
                doc.logical_document_id,
                doc.document_version_id,
                doc.generation,
            ) == (key.tenant_id, key.logical_document_id, key.document_version_id, key.generation):
                for block in doc.blocks:
                    if block.block_id == key.block_id:
                        return doc, block
        return None
