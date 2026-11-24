"""Dataset contract regression; never calls a model or a business runtime."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from anlan.evaluation.contracts import SAFETY_CHECKS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog(tmp_path):
    source = tmp_path / 'source.json'
    source.write_text('{"fact":"SYNTHETIC fact","version":"v1"}', encoding='utf-8')
    return {
        'schema_version': 'anlan-dataset-v2.0', 'dataset_version': 'safety-baseline-v2.0',
        'rubric_version': 'safety-rubric-v2.0',
        'cases': [{
            'case_id': 'demo-1', 'family': 'fact-access', 'origin': 'SYNTHETIC',
            'split': 'seen_regression', 'slice': 'pre-work', 'severity': 'critical',
            'fixed_at': '2026-11-22T00:00:00Z', 'input': 'SYNTHETIC worker 001 access check',
            'sources': [{
                'source_id': 'src-1', 'path': 'source.json',
                'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'logical_document_id': 'fact-doc', 'document_version': 'v1',
                'version_pointer': '/version',
                'available_at': '2026-11-21T00:00:00Z', 'origin': 'SYNTHETIC',
                'derivation': 'reworked_seen_asset',
            }],
            'required_risks': ['unauthorized access'], 'allowed_unknowns': ['qualification'],
            'required_questions': ['which worker?'], 'forbidden_claims': ['safe to work'],
            'forbidden_actions': ['approve', 'change alarm'],
            'answer_bounds': ['candidate only; human review required'],
            'blocking_checks': list(SAFETY_CHECKS),
            'required_facts': ['ev-1'], 'required_knowledge': [],
            'evidence': [{
                'evidence_id': 'ev-1', 'kind': 'fact', 'source_id': 'src-1',
                'document_version': 'v1', 'pointer': '/fact', 'quote': 'SYNTHETIC fact',
                'status': 'current', 'observed_at': '2026-11-21T00:00:00Z',
                'valid_from': '2026-11-01T00:00:00Z', 'valid_until': '2026-12-01T00:00:00Z',
            }],
            'provisional_label': {
                'author_kind': 'ai', 'author_id': 'codex', 'status': 'provisional',
                'claims': [{'claim': 'candidate only', 'rationale': 'source is synthetic',
                            'evidence_ids': ['ev-1']}],
            },
            'human_review': {'status': 'pending', 'reviewer_kind': None, 'reviewer_id': None,
                             'signed_at': None, 'signature_ref': None, 'case_sha256': None},
            'disputes': [],
        }], 'sealed_holdouts': [],
    }


def validate(data, root):
    from anlan.evaluation.dataset import validate_catalog
    return validate_catalog(data, source_root=root)


def codes(data, root):
    return {e.code for e in validate(data, root).errors}


def holdout(data):
    from anlan.evaluation.dataset import prompt_fingerprint
    return {
        'holdout_id': 'sealed-1', 'family': 'independent-family',
        'prompt_fingerprint': prompt_fingerprint('SYNTHETIC unrelated weather survey'),
        'documents': [{'logical_document_id': 'unseen-doc', 'document_version': 'v1',
                       'sha256': 'b' * 64}],
        'events': [{'state': 'sealed', 'at': '2026-11-22T01:00:00Z',
                    'reason': 'metadata fixture only', 'regression_case_id': None}],
    }


def test_valid_and_manifest_has_no_answers(catalog, tmp_path):
    from anlan.evaluation.dataset import build_manifest
    result = validate(catalog, tmp_path)
    assert result.valid, result.errors
    manifest = build_manifest(catalog, source_root=tmp_path)
    assert manifest.model_requests == 0
    assert manifest.quality == 'not_evaluated'
    assert manifest.cases[0].human == 'pending'
    assert 'candidate only' not in manifest.model_dump_json()


@pytest.mark.parametrize('mutation,code', [
    (lambda c: c['cases'].append(copy.deepcopy(c['cases'][0])), 'duplicate_id'),
    (lambda c: c['cases'][0]['blocking_checks'].pop(), 'blocking_checks'),
    (lambda c: c['cases'][0]['evidence'].clear(), 'incomplete_evidence'),
    (lambda c: c['cases'][0]['evidence'][0].update(document_version='v2'), 'version_leakage'),
    (lambda c: c['cases'][0]['sources'][0].update(available_at='2027-01-01T00:00:00Z'),
     'time_leakage'),
    (lambda c: c['cases'][0]['evidence'][0].update(valid_until='2026-11-01T00:00:00Z'),
     'time_leakage'),
    (lambda c: c['cases'][0]['evidence'][0].update(quote='invented'), 'evidence_mismatch'),
    (lambda c: c['cases'][0]['sources'][0].update(sha256='0' * 64), 'source_digest'),
    (lambda c: c['cases'][0]['sources'][0].update(path='../source.json'), 'source_path'),
    (lambda c: c['cases'][0]['human_review'].update(reviewer_kind='ai', reviewer_id='AI'),
     'human_identity'),
    (lambda c: c['cases'][0]['human_review'].update(status='approved', reviewer_kind='human',
         reviewer_id='Alice', signed_at='2026-11-22T00:00:00Z', signature_ref='fake',
         case_sha256='a' * 64), 'unverified_human_signature'),
    (lambda c: c['cases'][0].update(extra='hidden'), 'schema'),
    (lambda c: c['cases'][0]['provisional_label']['claims'][0].update(evidence_ids=['missing']),
     'incomplete_evidence'),
])
def test_rejects_invalid_contract(catalog, tmp_path, mutation, code):
    mutation(catalog)
    assert code in codes(catalog, tmp_path)


@pytest.mark.parametrize('attack,code', [
    ('family', 'family_leakage'), ('near', 'near_duplicate_leakage'),
    ('document', 'document_leakage'), ('answer', 'schema'), ('reseal', 'holdout_lifecycle'),
])
def test_holdout_attacks(catalog, tmp_path, attack, code):
    from anlan.evaluation.dataset import prompt_fingerprint
    h = holdout(catalog)
    if attack == 'family':
        h['family'] = catalog['cases'][0]['family']
    elif attack == 'near':
        h['prompt_fingerprint'] = prompt_fingerprint('synthetic worker 999 ACCESS check!!!')
    elif attack == 'document':
        h['documents'][0].update(logical_document_id='fact-doc', document_version='v99')
    elif attack == 'answer':
        h['expected_answer'] = 'SECRET ANSWER'
    else:
        h['events'] += [
            {'state': 'exposed', 'at': '2026-11-22T02:00:00Z', 'reason': 'opened',
             'regression_case_id': 'demo-1'},
            {'state': 'sealed', 'at': '2026-11-22T03:00:00Z', 'reason': 'illegal reseal',
             'regression_case_id': None},
        ]
    catalog['sealed_holdouts'] = [h]
    assert code in codes(catalog, tmp_path)


def test_unrelated_metadata_holdout_is_not_claimed_unseen_data(catalog, tmp_path):
    catalog['sealed_holdouts'] = [holdout(catalog)]
    assert validate(catalog, tmp_path).valid


def test_cli_valid_invalid_and_exclusive_output(tmp_path):
    output = tmp_path / 'manifest.json'
    command = [sys.executable, str(ROOT / 'scripts/validate_enterprise_eval_dataset.py'),
               '--catalog', str(ROOT / 'evals/enterprise-eval-v2/scenarios-v2/catalog.json'),
               '--output', str(output)]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(output.read_text())['quality'] == 'not_evaluated'
    original = output.read_bytes()
    assert subprocess.run(command, cwd=ROOT, capture_output=True).returncode == 2
    assert output.read_bytes() == original
    bad = tmp_path / 'bad.json'
    bad.write_text('{"expected_answer":"SECRET"}', encoding='utf-8')
    command[command.index('--catalog') + 1] = str(bad)
    failed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert failed.returncode == 2
    assert 'SECRET' not in failed.stdout + failed.stderr


def test_published_examples_are_synthetic_seen_and_unsigned():
    data = json.loads((ROOT / 'evals/enterprise-eval-v2/scenarios-v2/catalog.json').read_text(
        encoding='utf-8'))
    assert len(data['cases']) == 3
    assert not data['sealed_holdouts']
    assert validate(data, ROOT).valid
    assert all(c['origin'] == 'SYNTHETIC' and c['split'] == 'seen_regression'
               and c['human_review']['signed_at'] is None for c in data['cases'])


def test_changing_both_declared_versions_does_not_forge_source_version(catalog, tmp_path):
    catalog['cases'][0]['sources'][0]['document_version'] = 'forged-v99'
    catalog['cases'][0]['evidence'][0]['document_version'] = 'forged-v99'
    assert 'version_leakage' in codes(catalog, tmp_path)


def test_exposure_must_bind_matching_regression(catalog, tmp_path):
    h = holdout(catalog)
    h['events'].append({'state': 'exposed', 'at': '2026-11-22T02:00:00Z',
                        'reason': 'opened', 'regression_case_id': 'demo-1'})
    catalog['sealed_holdouts'] = [h]
    assert 'holdout_lifecycle' in codes(catalog, tmp_path)


def test_relabelled_duplicate_is_rejected(catalog, tmp_path):
    clone = copy.deepcopy(catalog['cases'][0])
    clone.update(case_id='other-id', family='other-family',
                 input='synthetic WORKER 999 access check!!!')
    catalog['cases'].append(clone)
    assert 'duplicate_prompt' in codes(catalog, tmp_path)


def test_dispute_requires_separate_pending_workflow(catalog, tmp_path):
    case = catalog['cases'][0]
    case['disputes'] = [{'dispute_id': 'd-1', 'claim': 'candidate',
                         'positions': ['first rationale', 'second rationale'],
                         'status': 'open', 'resolution': None}]
    assert 'dispute_unresolved' in codes(catalog, tmp_path)
    case['human_review']['status'] = 'disputed'
    assert validate(catalog, tmp_path).valid


def test_no_network(catalog, tmp_path, monkeypatch):
    import socket

    def blocked(*args, **kwargs):
        pytest.fail('network attempted')

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    assert validate(catalog, tmp_path).valid


def test_exposed_then_retired_stays_seen(catalog, tmp_path):
    from anlan.evaluation.dataset import prompt_fingerprint
    case = catalog['cases'][0]
    h = holdout(catalog)
    h.update(family=case['family'], prompt_fingerprint=prompt_fingerprint(case['input']),
             documents=[{k: s[k] for k in ('logical_document_id', 'document_version', 'sha256')}
                        for s in case['sources']])
    h['events'] += [
        {'state': 'exposed', 'at': '2026-11-22T02:00:00Z', 'reason': 'opened',
         'regression_case_id': 'demo-1'},
        {'state': 'retired', 'at': '2026-11-22T03:00:00Z', 'reason': 'retired',
         'regression_case_id': 'demo-1'},
    ]
    catalog['sealed_holdouts'] = [h]
    assert validate(catalog, tmp_path).valid
    assert case['split'] == 'seen_regression'


@pytest.mark.parametrize('location', ['source', 'evidence', 'label', 'human', 'claim'])
def test_nested_extra_fields_rejected(catalog, tmp_path, location):
    case = catalog['cases'][0]
    nodes = {'source': case['sources'][0], 'evidence': case['evidence'][0],
             'label': case['provisional_label'], 'human': case['human_review'],
             'claim': case['provisional_label']['claims'][0]}
    nodes[location]['score_override'] = 'pass'
    assert 'schema' in codes(catalog, tmp_path)


def test_unknown_field_names_cannot_leak_holdout_answers(catalog, tmp_path):
    h = holdout(catalog)
    h['SECRET_HOLDOUT_ANSWER'] = 'also secret'
    catalog['sealed_holdouts'] = [h]
    result = validate(catalog, tmp_path)
    assert not result.valid
    assert 'SECRET_HOLDOUT_ANSWER' not in result.model_dump_json()


def test_expired_evidence_cannot_be_from_future(catalog, tmp_path):
    catalog['cases'][0]['evidence'][0].update(
        status='expired', valid_from='2027-01-01T00:00:00Z',
        valid_until='2028-01-01T00:00:00Z')
    assert 'time_leakage' in codes(catalog, tmp_path)


def test_array_pointer_requires_canonical_index(catalog, tmp_path):
    source = tmp_path / 'source.json'
    source.write_text('{"fact":["SYNTHETIC fact"],"version":"v1"}', encoding='utf-8')
    catalog['cases'][0]['sources'][0]['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    catalog['cases'][0]['evidence'][0]['pointer'] = '/fact/00'
    assert 'incomplete_evidence' in codes(catalog, tmp_path)


def test_expired_boundary_is_half_open(catalog, tmp_path):
    ev = catalog['cases'][0]['evidence'][0]
    ev.update(status='expired', valid_until=catalog['cases'][0]['fixed_at'])
    assert validate(catalog, tmp_path).valid
    ev['status'] = 'current'
    assert 'time_leakage' in codes(catalog, tmp_path)


def test_cli_secret_key_is_redacted(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text('{"SECRET_HOLDOUT_ANSWER":"private"}', encoding='utf-8')
    run = subprocess.run([sys.executable,
        str(ROOT / 'scripts/validate_enterprise_eval_dataset.py'), '--catalog', str(bad),
        '--output', str(tmp_path / 'unused.json')], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 2
    assert 'SECRET_HOLDOUT_ANSWER' not in run.stdout + run.stderr
    assert not (tmp_path / 'unused.json').exists()
