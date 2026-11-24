"""Offline candidate contracts; no network, no legal or expert gold claims."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from anlan.knowledge.sources.contracts import SourceManifest
from anlan.knowledge.sources.validation import replay, validate_url

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / 'evals/safety-knowledge-v2/public-pilot'
BODY = b'SYNTHETIC safety case; not enterprise authority.\n'
URL = 'synthetic://public-pilot/sample.txt'


def candidate():
    return {
        'schema_version': 'public-sources-v1', 'manifest_version': '2026-11-22.1',
        'sources': [{
            'source_id': 'synthetic-test', 'publisher': 'Anlan synthetic fixture',
            'source_url': URL, 'retrieved_at': '2026-11-22T00:00:00Z',
            'upstream_revision': 'fixture-v1', 'revision_note': 'owned synthetic fixture',
            'content_kind': 'synthetic_case', 'validity': 'not_enterprise_authority',
            'review_state': 'candidate', 'access': 'offline_fixture',
            'data_origin': 'project_fixture',
            'import_policy': 'licensed_sample',
            'content_sha256': hashlib.sha256(BODY).hexdigest(),
            'license': {'identifier': 'CC0-1.0', 'redistribution': 'allowed',
                        'evidence_url': URL, 'evidence_note': 'Project authored fixture only'},
        }],
    }


@pytest.mark.parametrize('field', ['source_url', 'evidence_url'])
def test_fixture_cannot_claim_official_https_source(field):
    data = candidate()
    source = data['sources'][0]
    target = source if field == 'source_url' else source['license']
    target[field] = 'https://www.mem.gov.cn/pilot.txt'
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize('field,value', [
    ('access', 'public_web'), ('content_kind', 'accident_case'),
    ('data_origin', 'public_source'),
])
def test_synthetic_uri_requires_all_fixture_markers(field, value):
    data = candidate()
    data['sources'][0][field] = value
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize('field', ['source_url', 'evidence_url'])
def test_public_source_cannot_use_synthetic_uri(field):
    data = candidate()
    source = data['sources'][0]
    source.update(access='public_web', content_kind='accident_case', data_origin='public_source',
                  source_url='https://www.mem.gov.cn/report.txt')
    source['license']['evidence_url'] = 'https://www.mem.gov.cn/report.txt'
    target = source if field == 'source_url' else source['license']
    target[field] = URL
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize('uri', [
    'synthetic://www.mem.gov.cn/sample.txt', 'synthetic://public-pilot/../sample.txt',
    'synthetic://public-pilot/sample.txt?x=1', 'synthetic://user@public-pilot/sample.txt',
    'synthetic://public-pilot/%73ample.txt', 'synthetic://public-pilot/sample.txt#x',
])
def test_synthetic_uri_still_has_strict_syntax(uri):
    data = candidate()
    data['sources'][0]['source_url'] = uri
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


def test_candidate_contract_and_receipt_are_read_only():
    manifest = SourceManifest.model_validate(candidate())
    source = manifest.sources[0]
    receipt = replay(source, BODY, final_url=URL, status=200, content_type='text/plain')
    assert receipt.review_state == 'candidate'
    assert receipt.sha256 == hashlib.sha256(BODY).hexdigest()
    with pytest.raises(ValidationError):
        source.review_state = 'published'


@pytest.mark.parametrize('url', [
    'http://www.mem.gov.cn/a', 'https://127.0.0.1/a', 'https://[::1]/a',
    'https://www.mem.gov.cn.evil.test/a', 'https://user:pass@www.mem.gov.cn/a',
    'https://www.mem.gov.cn:443/a', 'file:///tmp/a', 'https://www.mem.gov.cn/a#b',
    'https://www.mem.gov.cn/a?token=secret', 'https://www.mem.gov.cn/%2e%2e/a',
    'https://www.mem.gov.cn/../a', 'https://www.mem.gov.cn/\\evil',
    'https://www.mem.gov.cn/\na', 'https://www.mem.gov.cn./a',
])
def test_malicious_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize('field,value', [
    ('review_state', 'published'), ('validity', 'current'),
    ('retrieved_at', '2026-11-22T00:00:00'), ('content_sha256', 'bad'),
    ('upstream_revision', ''), ('publisher', ''), ('unexpected', True),
])
def test_bad_manifest_fields_rejected(field, value):
    data = candidate()
    data['sources'][0][field] = value
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


def test_duplicate_source_ids_and_missing_license_rejected():
    data = candidate()
    data['sources'].append(data['sources'][0])
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)
    data = candidate()
    del data['sources'][0]['license']
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize('change', [
    {'final_url': 'https://www.mem.gov.cn/other.txt'}, {'status': 302},
    {'redirected': True}, {'content_type': 'application/pdf'},
    {'content_type': 'text/html'}, {'content_encoding': 'gzip'},
    {'body': b'x' * 65537}, {'body': b'changed'}, {'body': b'\xff'},
    {'body': b''}, {'body': b'\x00'},
])
def test_replay_rejects_untrusted_response(change):
    source = SourceManifest.model_validate(candidate()).sources[0]
    kwargs = dict(body=BODY, final_url=URL, status=200, content_type='text/plain')
    kwargs.update(change)
    with pytest.raises(ValueError):
        replay(source, **kwargs)


@pytest.mark.parametrize('change', [
    'unknown_license', 'denied_license', 'metadata_only', 'no_revision', 'no_hash',
])
def test_unlicensed_or_unpinned_source_cannot_import(change):
    data = candidate()
    source = data['sources'][0]
    if change in {'unknown_license', 'denied_license'}:
        source['license']['redistribution'] = change.removesuffix('_license')
    elif change == 'metadata_only':
        source['import_policy'] = 'metadata_only'
    elif change == 'no_revision':
        source['upstream_revision'] = None
    else:
        source['content_sha256'] = None
    with pytest.raises(ValueError):
        replay(SourceManifest.model_validate(data).sources[0], BODY,
               final_url=URL, status=200, content_type='text/plain')


@pytest.mark.parametrize('field', ['identifier', 'evidence_note'])
def test_whitespace_is_not_license_evidence(field):
    data = candidate()
    data['sources'][0]['license'][field] = '   '
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


@pytest.mark.parametrize('field', ['source_url', 'evidence_url'])
@pytest.mark.parametrize('url', [' ' + URL, '\n' + URL, URL + '\r\n'])
def test_manifest_does_not_silently_trim_a_url(field, url):
    data = candidate()
    target = data['sources'][0] if field == 'source_url' else data['sources'][0]['license']
    target[field] = url
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(data)


def test_cli_rejects_linked_sample_path(monkeypatch, tmp_path):
    script = ROOT / 'scripts/curate_public_safety_corpus.py'
    spec = importlib.util.spec_from_file_location('public_corpus_cli', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(candidate()), encoding='utf-8')
    sample = tmp_path / 'sample.txt'
    sample.write_bytes(BODY)
    # Portable simulation of a symlink without requiring Windows symlink privilege.
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == sample or original(p))
    monkeypatch.setattr(sys, 'argv', [str(script), 'replay', str(manifest),
                                     '--source-id', 'synthetic-test', '--file', 'sample.txt'])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


def test_checked_in_manifest_and_offline_cli(tmp_path):
    manifest = PILOT / 'manifest.json'
    data = SourceManifest.model_validate_json(manifest.read_bytes())
    assert all(s.review_state == 'candidate' for s in data.sources)
    assert all(s.import_policy == 'metadata_only' for s in data.sources
               if s.content_kind != 'synthetic_case')
    script = ROOT / 'scripts/curate_public_safety_corpus.py'
    result = subprocess.run([sys.executable, str(script), 'validate', str(manifest)],
                            capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['state'] == 'candidate'
    result = subprocess.run([sys.executable, str(script), 'replay', str(manifest),
                             '--source-id', 'synthetic-pilot-v1', '--file', 'sample.txt'],
                            capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['review_state'] == 'candidate'
    for name in ['../outside.txt', str(tmp_path / 'outside.txt')]:
        result = subprocess.run([sys.executable, str(script), 'replay', str(manifest),
                                 '--source-id', 'synthetic-pilot-v1', '--file', name],
                                capture_output=True, text=True, cwd=tmp_path)
        assert result.returncode != 0
