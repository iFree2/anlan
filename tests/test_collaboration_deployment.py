import copy
import importlib.util
import types
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

MODULE = Path(__file__).resolve().parents[1] / 'deploy/aliyun/release_collaboration.py'
spec = importlib.util.spec_from_file_location('p12_deploy', MODULE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_budget_plan_uses_actual_ledger_and_counts_failed_and_reserved():
    ledger = {'total': 79, 'conversation': 12, 'materials_events': 3,
              'total_limit': 100, 'conversation_limit': 30, 'materials_events_limit': 10}
    assert release.live_plan(ledger) == {'conversation': 7, 'materials': 2, 'event': 1}
    for field, value in [('total', 91), ('conversation', 24), ('materials_events', 8)]:
        with pytest.raises(RuntimeError, match='Insufficient'):
            release.live_plan(ledger | {field: value})
    with pytest.raises(RuntimeError, match='authorization'):
        release.live_plan(ledger | {'total_limit': 101})


def test_preflight_refuses_unfinished_work_instead_of_replaying_it():
    for key in ('pending_operations', 'pending_messages', 'pending_reviews', 'reserved_attempts'):
        with pytest.raises(RuntimeError, match='Unfinished'):
            release.require_quiescent({key: 1})
    release.require_quiescent(dict.fromkeys(('pending_operations', 'pending_messages',
                              'pending_reviews', 'reserved_attempts'), 0))


def test_new_identity_config_preserves_legacy_token_role_and_profile():
    old = {'schema_version': 'local-service-v1', 'tokens': [{'token': 'x' * 48,
           'identity': {'tenant_id': 'old', 'user_id': 'old'}}],
           'console_profiles': [], 'model_mode': 'deepseek_live'}
    original = copy.deepcopy(old)
    config, clients = release.dual_config(old, {}, Path('/new/facts'))
    assert old == original
    assert config['tokens'][0] == old['tokens'][0]
    assert 'collaboration_role' not in config['tokens'][0]
    assert len(clients) == 2
    grants = [document['tokens'][0] for document in clients.values()]
    assert {g['collaboration_role'] for g in grants} == {'applicant', 'safety_manager'}
    assert len({g['token'] for g in grants} | {'x' * 48}) == 3
    assert len({g['identity']['user_id'] for g in grants}) == 2
    assert grants[0]['identity']['tenant_id'] == grants[1]['identity']['tenant_id'] != 'old'


def test_synthetic_facts_are_added_without_retagging_legacy_records():
    legacy = {'records': [{'tenant_id': 'legacy', 'value': 1}]}
    fixture = {'records': [{'tenant_id': 'source', 'value': 2}]}
    result = release.merge_facts(legacy, fixture, 'new')
    assert result['records'] == [{'tenant_id': 'legacy', 'value': 1},
                                 {'tenant_id': 'new', 'value': 2}]
    assert legacy['records'][0]['tenant_id'] == 'legacy'
    assert fixture['records'][0]['tenant_id'] == 'source'


def test_new_collaboration_requires_maintenance_rollback_for_every_old_write_path():
    module = types.ModuleType('maintenance')
    exec(release.MAINTENANCE_SOURCE, module.__dict__)
    with TestClient(module.create_app()) as client:
        for path in ('/tasks/t/resume', '/tasks/t/revise', '/tasks/t/recover',
                     '/conversations/c/messages', '/collaboration/applications/t/commands/submit',
                     '/console/api/tasks/t/events', '/events/e/reviews', '/unknown'):
            for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                response = client.request(method, path, json={})
                assert response.status_code == 503
                assert response.json()['mode'] == 'maintenance'
        assert client.get('/health/ready').json() == {'status': 'maintenance', 'writable': False}


def test_rollback_never_switches_to_legacy_or_restores_database(monkeypatch, tmp_path):
    fallback = tmp_path / 'maintenance'
    fallback.mkdir()
    monkeypatch.setattr(release, 'MAINTENANCE', fallback)
    observed = []
    monkeypatch.setattr(release, 'command', lambda *args, **kwargs: observed.append(args))
    monkeypatch.setattr(release, 'switch_release', lambda path: observed.append(path))
    monkeypatch.setattr(release, 'wait_maintenance', lambda: observed.append('verified-503'))
    assert release.rollback()['database_preserved'] is True
    assert fallback in observed and observed[-1] == 'verified-503'
    assert not any('pg_restore' in str(item) for item in observed)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../../escape', 'a\\..\\escape'])
def test_wheel_traversal_is_rejected_before_extract(tmp_path, name):
    wheel = tmp_path / 'bad.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr(name, 'bad')
    with pytest.raises(RuntimeError, match='Unsafe'):
        release.validate_wheel(wheel, release.digest(wheel.read_bytes()))


def test_activation_rejects_changed_data_and_missing_backup():
    manifest = {'status': 'prepared', 'database_dump_sha256': 'verified'}
    before = {'rows': {'model_budget_attempts': ['old']}}
    release.activation_gate(manifest, before, before)
    with pytest.raises(RuntimeError, match='changed'):
        release.activation_gate(manifest, before, {'rows': {'model_budget_attempts': []}})
    with pytest.raises(RuntimeError, match='backup'):
        release.activation_gate({'status': 'prepared'}, before, before)
