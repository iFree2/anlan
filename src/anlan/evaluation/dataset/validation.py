"""Offline integrity/leakage checks; no semantic or human authenticity claims."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from anlan.evaluation.contracts import SAFETY_CHECKS

from .contracts import Catalog, ValidationIssue, ValidationResult


def prompt_fingerprint(prompt: str) -> str:
    """64-bit SimHash of normalized character trigrams; a leakage heuristic only."""
    normalized = unicodedata.normalize('NFKC', prompt).casefold()
    normalized = re.sub(r'\d+', '#', normalized)
    normalized = ''.join(c for c in normalized if c.isalnum() or c == '#')
    grams = {normalized[i:i + 3] for i in range(max(1, len(normalized) - 2))}
    weights = [0] * 64
    for gram in grams:
        value = int.from_bytes(hashlib.sha256(gram.encode()).digest()[:8])
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    return f'{sum(1 << b for b, w in enumerate(weights) if w >= 0):016x}'


def _pointer(value, pointer):
    if not pointer.startswith('/'):
        raise ValueError('invalid pointer')
    for part in pointer[1:].split('/'):
        if re.search(r'~(?![01])', part):
            raise ValueError('invalid pointer escape')
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', part):
                raise ValueError('invalid array pointer')
            value = value[int(part)]
        else:
            value = value[part]
    return value


def validate_catalog(data: dict, *, source_root: Path) -> ValidationResult:
    errors = []

    def issue(code, path):
        errors.append(ValidationIssue(code=code, path=path))

    try:
        catalog = Catalog.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False):
            parts = list(error['loc'])
            if error['type'] == 'extra_forbidden':
                parts[-1] = '<extra>'  # untrusted key names may themselves contain answers
            location = '.'.join(map(str, parts))
            code = 'incomplete_evidence' if location.endswith('.evidence') else 'schema'
            issue(code, location or 'catalog')
        return ValidationResult(valid=False, errors=errors)

    def unique(values, path):
        if len(values) != len(set(values)):
            issue('duplicate_id', path)

    unique([c.case_id for c in catalog.cases] + [h.holdout_id for h in catalog.sealed_holdouts],
           'catalog.ids')
    fingerprints = [prompt_fingerprint(c.input) for c in catalog.cases]
    if len(fingerprints) != len(set(fingerprints)):
        issue('duplicate_prompt', 'cases')
    root = source_root.resolve()
    for index, case in enumerate(catalog.cases):
        p = f'cases.{index}'
        if set(case.blocking_checks) != set(SAFETY_CHECKS) or len(case.blocking_checks) != 9:
            issue('blocking_checks', p)
        for key in ('source_id', 'evidence_id', 'dispute_id'):
            items = {'source_id': case.sources, 'evidence_id': case.evidence,
                     'dispute_id': case.disputes}[key]
            unique([getattr(item, key) for item in items], f'{p}.{key}')
        sources = {s.source_id: s for s in case.sources}
        loaded = {}
        for source in case.sources:
            sp = f'{p}.sources'
            path = PurePosixPath(source.path)
            if (path.is_absolute() or '..' in path.parts or ':' in source.path
                    or '\\' in source.path):
                issue('source_path', sp)
                continue
            target = (root / source.path).resolve()
            if not target.is_relative_to(root) or target.suffix != '.json':
                issue('source_path', sp)
                continue
            if source.available_at > case.fixed_at:
                issue('time_leakage', sp)
            try:
                raw = target.read_bytes()
                if hashlib.sha256(raw).hexdigest() != source.sha256:
                    issue('source_digest', sp)
                    continue
                loaded[source.source_id] = json.loads(raw)
                try:
                    if _pointer(loaded[source.source_id], source.version_pointer) != (
                            source.document_version):
                        issue('version_leakage', sp)
                except (KeyError, IndexError, TypeError, ValueError):
                    issue('version_leakage', sp)
            except (OSError, ValueError):
                issue('source_unreadable', sp)
        evidence = {e.evidence_id: e for e in case.evidence}
        for ids, kind in ((case.required_facts, 'fact'), (case.required_knowledge, 'knowledge')):
            for eid in ids:
                if eid not in evidence or evidence[eid].kind != kind:
                    issue('incomplete_evidence', p)
        if not case.required_facts and not case.required_knowledge:
            issue('incomplete_evidence', p)
        for ev in case.evidence:
            source = sources.get(ev.source_id)
            if source is None:
                issue('incomplete_evidence', p)
                continue
            if ev.document_version != source.document_version:
                issue('version_leakage', p)
            if (ev.observed_at > case.fixed_at or ev.valid_from >= ev.valid_until
                    or (ev.status == 'expired' and ev.valid_until > case.fixed_at)
                    or (ev.status == 'current' and not
                        ev.valid_from <= case.fixed_at < ev.valid_until)):
                issue('time_leakage', p)
            try:
                actual = _pointer(loaded[ev.source_id], ev.pointer)
                if not isinstance(actual, str) or ev.quote not in actual:
                    issue('evidence_mismatch', p)
            except (KeyError, IndexError, TypeError, ValueError):
                issue('incomplete_evidence', p)
        for claim in case.provisional_label.claims:
            if not set(claim.evidence_ids) <= evidence.keys():
                issue('incomplete_evidence', p)
        human = case.human_review
        if human.reviewer_kind == 'ai':
            issue('human_identity', p)
        if (human.status == 'approved' or human.signed_at is not None
                or human.signature_ref is not None or human.case_sha256 is not None):
            issue('unverified_human_signature', p)
        if human.reviewer_id is not None or human.reviewer_kind is not None:
            issue('human_identity', p)
        for dispute in case.disputes:
            if (dispute.status == 'resolved') != (dispute.resolution is not None):
                issue('dispute_resolution', p)
        if any(d.status == 'open' for d in case.disputes) and human.status != 'disputed':
            issue('dispute_unresolved', p)
        if human.status == 'disputed' and not any(d.status == 'open' for d in case.disputes):
            issue('dispute_unresolved', p)

    case_ids = {c.case_id for c in catalog.cases}
    for i, h in enumerate(catalog.sealed_holdouts):
        p = f'sealed_holdouts.{i}'
        states = [e.state for e in h.events]
        if states not in (['sealed'], ['sealed', 'exposed'], ['sealed', 'exposed', 'retired']):
            issue('holdout_lifecycle', p)
        if any(a.at >= b.at for a, b in zip(h.events, h.events[1:])):
            issue('holdout_lifecycle', p)
        for event in h.events:
            if ((event.state == 'sealed' and event.regression_case_id is not None)
                    or (event.state != 'sealed' and event.regression_case_id not in case_ids)):
                issue('holdout_lifecycle', p)
            if event.state != 'sealed' and event.regression_case_id in case_ids:
                seen = next(c for c in catalog.cases if c.case_id == event.regression_case_id)
                if (seen.family != h.family
                        or prompt_fingerprint(seen.input) != h.prompt_fingerprint
                        or {(s.logical_document_id, s.document_version, s.sha256)
                            for s in seen.sources} != {
                                (d.logical_document_id, d.document_version, d.sha256)
                                for d in h.documents}):
                    issue('holdout_lifecycle', p)
        if h.events[-1].state != 'sealed':
            continue  # exposed records are already in the seen partition
        for c in catalog.cases:
            if c.family == h.family:
                issue('family_leakage', p)
            distance = (int(prompt_fingerprint(c.input), 16)
                        ^ int(h.prompt_fingerprint, 16)).bit_count()
            if distance <= 3:
                issue('near_duplicate_leakage', p)
            if any(s.logical_document_id == d.logical_document_id or s.sha256 == d.sha256
                   for s in c.sources for d in h.documents):
                issue('document_leakage', p)
    return ValidationResult(valid=not errors, errors=errors)
