"""Release Gate rejects live configuration and verifies real wheel process recovery."""

import importlib.util
from pathlib import Path

import pytest
from test_events_postgres import dsn  # noqa: F401


def verifier():
    spec = importlib.util.spec_from_file_location(
        'collaboration_release', 'scripts/verify_collaboration_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight_verifier():
    spec = importlib.util.spec_from_file_location(
        'preflight_release', 'scripts/verify_preflight_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StartupBlocked(Exception):
    """Offline tests must never spawn a child or connect to any database/network."""


@pytest.fixture
def offline_gate(tmp_path, monkeypatch):
    import json
    import os
    import socket
    import zipfile

    import psycopg

    module = verifier()
    for name in os.environ:
        if name.upper().startswith('PG'):
            monkeypatch.delenv(name)
    wheel = tmp_path / 'offline.whl'
    with zipfile.ZipFile(wheel, 'w'):
        pass
    config = tmp_path / 'scripted.json'
    config.write_text(json.dumps({'model_mode': 'scripted_double', 'tokens': [
        {'token': role, 'identity': {'tenant_id': 'offline', 'user_id': role},
         'collaboration_role': role} for role in ('applicant', 'safety_manager')]}),
        encoding='utf-8')
    monkeypatch.setattr(module, 'verify_resources', lambda *_: [])
    starts = []

    def block_start(*args, **kwargs):
        starts.append(kwargs)
        raise StartupBlocked('offline process boundary')

    def block_connect(*args, **kwargs):
        raise AssertionError('offline test attempted a connection')

    monkeypatch.setattr(module.subprocess, 'Popen', block_start)
    monkeypatch.setattr(psycopg, 'connect', block_connect)
    monkeypatch.setattr(psycopg.Connection, 'connect', block_connect)
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', block_connect)
    monkeypatch.setattr(socket.socket, 'connect', block_connect)
    monkeypatch.setattr(socket, 'getaddrinfo', block_connect)
    return module, wheel, config, starts


UNSAFE_TARGETS = [
    pytest.param('host=203.0.113.10 dbname=demo', {}, id='remote-ipv4'),
    pytest.param('host=2001:db8::1 dbname=demo', {}, id='remote-ipv6'),
    pytest.param('host=db.example.invalid dbname=demo', {}, id='remote-dns'),
    pytest.param('host=localhost hostaddr=203.0.113.10 dbname=demo', {}, id='hostaddr-wins'),
    pytest.param('host=db.example.invalid hostaddr=127.0.0.1', {}, id='remote-host-label'),
    pytest.param('host=localhost hostaddr=::ffff:203.0.113.10', {}, id='mapped-remote'),
    pytest.param('host=localhost,203.0.113.10', {}, id='mixed-hosts'),
    pytest.param('host=127.0.0.1,::1', {}, id='unsupported-local-multihost'),
    pytest.param('host=localhost hostaddr=127.0.0.1,203.0.113.10', {}, id='mixed-addresses'),
    pytest.param('host=localhost port=5432,55432', {}, id='multiple-ports'),
    pytest.param('host=localhost port=0', {}, id='zero-port'),
    pytest.param('host=localhost port=65536', {}, id='invalid-port'),
    pytest.param('host=localhost port=invalid', {}, id='nonnumeric-port'),
    pytest.param('host=localhost port=\'\'', {}, id='empty-port'),
    pytest.param('host=localhost hostaddr=\'\'', {}, id='empty-hostaddr'),
    pytest.param('dbname=demo', {}, id='implicit-target'),
    pytest.param('', {}, id='empty-dsn'),
    pytest.param('host=\'\' dbname=demo', {}, id='empty-host'),
    pytest.param('host=/tmp dbname=demo', {}, id='unsupported-socket'),
    pytest.param('host=localhost.localdomain', {}, id='untrusted-localhost-alias'),
    pytest.param('host=localhost service=offline-remote', {}, id='dsn-service'),
    pytest.param('postgresql://localhost/demo?service=offline-remote', {}, id='uri-service'),
    pytest.param('host=localhost password=PRIVATE-TARGET-SENTINEL unknown_option=x', {},
                 id='invalid-dsn-redacts-secrets'),
    *[pytest.param('host=localhost dbname=demo', {name: 'PRIVATE-TARGET-SENTINEL'},
                   id='environment-' + name.lower()) for name in (
                       'PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGOPTIONS',
                       'PGSERVICE', 'PGSERVICEFILE', 'PGSYSCONFDIR', 'PGPASSWORD')],
]


@pytest.mark.parametrize('entry', ['verify', 'start'])
@pytest.mark.parametrize('target_dsn,overrides', UNSAFE_TARGETS)
def test_release_target_rejected_before_any_process_or_connection(
    offline_gate, monkeypatch, tmp_path, entry, target_dsn, overrides,
):
    import traceback

    module, wheel, config, starts = offline_gate
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match='loopback') as error:
        if entry == 'verify':
            module.verify(wheel, config, target_dsn)
        else:
            module.WheelServer(wheel, config, target_dsn, tmp_path, 1).start()
    assert starts == []
    rendered = ''.join(traceback.format_exception(error.value))
    assert 'PRIVATE-TARGET-SENTINEL' not in rendered
    assert '203.0.113.10' not in str(error.value)


@pytest.mark.parametrize('target_dsn,address,port', [
    ('postgresql://127.0.0.1:55432/demo', '127.0.0.1', '55432'),
    ('host=localhost dbname=demo', '127.0.0.1', '5432'),
    ('postgresql://[::1]:55432/demo', '::1', '55432'),
    ('host=localhost hostaddr=::1 port=55432 dbname=demo', '::1', '55432'),
    ('host=127.7.8.9 port=5432 dbname=demo', '127.7.8.9', '5432'),
])
def test_release_explicit_loopback_pins_address_and_cleans_child_environment(
    offline_gate, monkeypatch, target_dsn, address, port,
):
    from psycopg.conninfo import conninfo_to_dict

    module, wheel, config, starts = offline_gate
    monkeypatch.setenv('PGHOSTADDR', '')  # Empty is unset in libpq; still remove it from child.
    monkeypatch.setenv('PGSERVICE', '')
    with pytest.raises(StartupBlocked):
        module.verify(wheel, config, target_dsn)
    assert len(starts) == 1
    child = starts[0]['env']
    assert not any(name.upper().startswith('PG') for name in child)
    params = conninfo_to_dict(child['ANLAN_DATABASE_URL'])
    assert params['hostaddr'] == address and params['port'] == port
    assert 'service' not in params


def test_release_rechecks_environment_at_process_start(offline_gate, monkeypatch):
    module, wheel, config, starts = offline_gate

    def change_environment(*args):
        monkeypatch.setenv('PGHOSTADDR', '203.0.113.10')
        return []

    monkeypatch.setattr(module, 'verify_resources', change_environment)
    with pytest.raises(ValueError, match='loopback'):
        module.verify(wheel, config, 'host=localhost dbname=demo')
    assert starts == []


@pytest.mark.parametrize('winerror,failures,expected_calls', [
    (32, 2, 3), (32, 100, 40), (5, 1, 1),
])
def test_release_cleanup_only_waits_boundedly_for_windows_directory_release(
    monkeypatch, tmp_path, winerror, failures, expected_calls,
):
    module = verifier()
    calls, waits = [], []
    directory = tmp_path / 'anlan-b4-wheel-owned'
    directory.mkdir()

    def cleanup(path):
        assert path == directory
        calls.append('cleanup-owned-temporary-directory')
        if len(calls) <= failures:
            error = PermissionError('synthetic directory release window')
            error.winerror = winerror
            raise error

    monkeypatch.setattr(module.time, 'sleep', waits.append)
    monkeypatch.setattr(module.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(module.shutil, 'rmtree', cleanup)
    if failures < expected_calls:
        assert module.cleanup_directory(directory, processes_stopped=True) == expected_calls
    else:
        with pytest.raises(PermissionError):
            module.cleanup_directory(directory, processes_stopped=True)
    assert len(calls) == expected_calls
    assert len(waits) == expected_calls - 1
    assert sum(waits) <= 2


@pytest.mark.parametrize('stopped,owned', [(False, True), (True, False)])
def test_release_cleanup_refuses_unverified_exit_or_foreign_path(
    monkeypatch, tmp_path, stopped, owned,
):
    module = verifier()
    monkeypatch.setattr(module.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(module.shutil, 'rmtree', lambda *_: pytest.fail('Unsafe cleanup'))
    target = tmp_path / 'anlan-b4-wheel-owned' if owned else tmp_path.parent / 'foreign'
    with pytest.raises((ValueError, RuntimeError)):
        module.cleanup_directory(target, processes_stopped=stopped)


@pytest.mark.parametrize('serving_pid', [42, 43])
def test_release_uses_direct_runtime_and_rejects_launcher_serving_pid_mismatch(
    offline_gate, monkeypatch, tmp_path, serving_pid,
):
    import json
    import sys
    import sysconfig
    from types import SimpleNamespace

    module, wheel, config, _ = offline_gate

    def launch(args, **kwargs):
        assert Path(args[0]).resolve() == Path(sys._base_executable).resolve()
        assert args[9] == sysconfig.get_path('purelib')
        generation = args[10]
        marker = {'pid': serving_pid, 'generation': generation,
                  'module_file': str(wheel) + '/anlan/__init__.py', 'knowledge': 'offline_double'}
        Path(args[8]).write_text(json.dumps(marker), encoding='utf-8')
        monkeypatch.setattr(module.httpx, 'get', lambda *a, **k: SimpleNamespace(
            status_code=200, json=lambda: {'pid': serving_pid, 'generation': generation}))
        return SimpleNamespace(pid=42, poll=lambda: None)

    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    server = module.WheelServer(wheel, config, 'host=localhost', tmp_path, 1)
    if serving_pid != 42:
        with pytest.raises(RuntimeError, match='PID'):
            server.start()
    else:
        server.start()
        assert server.history[-1]['launched_pid'] == server.history[-1]['pid'] == 42


@pytest.mark.parametrize('exit_kind', ['normal', 'kill', 'crash', 'occupied_port'])
def test_release_stop_waits_for_owned_process_and_closed_port(monkeypatch, tmp_path, exit_kind):
    from types import SimpleNamespace

    module = verifier()
    calls = []

    def wait(**kwargs):
        calls.append('wait')
        if exit_kind == 'kill' and calls.count('wait') == 1:
            raise module.subprocess.TimeoutExpired('owned process', 10)
        return 91 if exit_kind == 'crash' else 0

    def closed(port):
        calls.append('port')
        return exit_kind != 'occupied_port'

    process = SimpleNamespace(pid=42, poll=lambda: 91 if exit_kind == 'crash' else None,
        terminate=lambda: calls.append('terminate'), kill=lambda: calls.append('kill'), wait=wait)
    server = module.WheelServer(Path('wheel'), Path('config'), 'host=localhost', tmp_path, 1)
    server.process = process
    server.history.append({'launched_pid': 42, 'pid': 42})
    monkeypatch.setattr(module, 'port_closed', closed, raising=False)
    if exit_kind == 'occupied_port':
        with pytest.raises(RuntimeError, match='port'):
            server.stop()
    else:
        server.stop()
        assert server.history[-1]['exit_verified'] and server.history[-1]['port_closed']
        assert calls[-1] == 'port'
        if exit_kind == 'kill':
            assert calls == ['terminate', 'wait', 'kill', 'wait', 'port']


@pytest.mark.parametrize('code,closed', [(10061, True), (10060, False), (10013, False)])
def test_release_port_probe_does_not_treat_timeout_or_denial_as_closed(monkeypatch, code, closed):
    module = verifier()

    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, timeout):
            pass

        def connect_ex(self, target):
            assert target[0] == '127.0.0.1'
            return code

    monkeypatch.setattr(module.socket, 'socket', Probe)
    if closed:
        assert module.socket_listening(1) is False
    else:
        with pytest.raises(OSError):
            module.socket_listening(1)


def test_release_port_check_matches_an_actual_owned_listener():
    import socket

    module = verifier()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert module.port_closed(port) is False
    assert module.port_closed(port) is True


@pytest.mark.parametrize('mode', ['deepseek_live', None])
def test_release_gate_requires_explicit_scripted_mode(mode):
    with pytest.raises(ValueError, match='scripted'):
        verifier().validate_config({'model_mode': mode, 'tokens': []})


def test_release_gate_requires_distinct_same_tenant_participants():
    grants = [{'identity': {'tenant_id': 't', 'user_id': 'same'},
               'collaboration_role': role} for role in ('applicant', 'safety_manager')]
    with pytest.raises(ValueError, match='distinct'):
        verifier().validate_config({'model_mode': 'scripted_double', 'tokens': grants})


def test_release_gate_does_not_reuse_evidence_directory(tmp_path):
    with pytest.raises(FileExistsError):
        verifier().new_evidence_directory(tmp_path)


def test_release_resources_include_and_validate_console_static_bytes(tmp_path):
    import zipfile

    root = Path.cwd()
    assets = list((root / 'src/anlan/interfaces/console/assets').rglob('*'))
    resources = [*(root / 'src/anlan/sql').glob('*.sql'),
                 *(root / 'src/anlan/assets').glob('*'), *[p for p in assets if p.is_file()]]
    target = tmp_path / 'resources.whl'

    def archive(corrupt=False):
        with zipfile.ZipFile(target, 'w') as output:
            for resource in resources:
                name = resource.relative_to(root / 'src').as_posix()
                output.writestr(name, b'corrupt' if corrupt and name.endswith('/api.js')
                                else resource.read_bytes())

    archive()
    with zipfile.ZipFile(target) as package:
        checked = verifier().verify_resources(package, root)
    assert {p.relative_to(root / 'src').as_posix() for p in assets if p.is_file()} <= {
        item['path'] for item in checked}
    archive(corrupt=True)
    with zipfile.ZipFile(target) as package, pytest.raises(ValueError, match='differs'):
        verifier().verify_resources(package, root)


def test_poll_json_key_order_does_not_rebuild_frozen_card(tmp_path):
    import shutil
    import subprocess

    harness = tmp_path / 'snapshot-order.cjs'
    harness.write_text('''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const before = {conversation_id:'own', revision:4, status:'pending_confirmation',
  pending_intent:{collaboration:{task_id:'same', action:'resubmit', payload:{
    request_id:'frozen', expected_application_version:3, expected_material_revision:2,
    reply:'SYNTHETIC unchanged reply'}}}, messages:[]};
function reorder(value) {
  if (Array.isArray(value)) return value.map(reorder);
  if (value && typeof value === 'object') return Object.fromEntries(
    Object.keys(value).reverse().map(key => [key, reorder(value[key])]));
  return value;
}
const elements = new Map();
const context = {renders:0, AbortController, clearTimeout(){},
  request:async () => reorder(before),
  document:{querySelectorAll:() => [], getElementById:id => {
    if (!elements.has(id)) elements.set(id,{addEventListener(){},replaceChildren(){}});
    return elements.get(id);
  }}};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], 'utf8').replace(/^import .*\\r?\\n/, '');
vm.runInContext(source + `
state.snapshot = ${JSON.stringify(before)};
renderSnapshot = () => {globalThis.renders++;};
loadEvents = async () => {};
globalThis.refresh = refreshConversation;
`, context);
(async () => {
  await context.refresh({quiet:true});
  assert.equal(context.renders,0,'JSON object order rebuilt the frozen confirmation card');
  context.request = async () => ({...reorder(before), revision:5});
  await context.refresh({quiet:true});
  assert.equal(context.renders,1,'A real revision change must still update the view');
})().catch(error => {console.error(error);process.exitCode=1;});
''', encoding='utf-8')
    result = subprocess.run([shutil.which('node') or 'node', str(harness),
        str(Path('src/anlan/interfaces/console/assets/app.js').resolve())],
        capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.postgres
def test_wheel_process_restarts_preserve_frozen_commands_and_committed_replay(
    dsn, tmp_path,  # noqa: F811
):
    import asyncio
    import json
    import os
    import subprocess

    from anlan.common.models import Identity
    from anlan.interfaces.service_config import ServiceConfig
    from anlan.knowledge.embeddings import LocalEmbeddings
    from anlan.knowledge.store import KnowledgeStore

    wheel = os.environ.get('ANLAN_B4_TEST_WHEEL')
    config = os.environ.get('ANLAN_B4_TEST_CONFIG')
    if not wheel:
        subprocess.run(['uv', 'build', '--wheel', '--out-dir', str(tmp_path / 'dist')],
                       check=True, capture_output=True, timeout=60)
        wheel = str(next((tmp_path / 'dist').glob('*.whl')))
    if not config:
        spec = importlib.util.spec_from_file_location(
            'prepare_demo', 'scripts/prepare_collaboration_demo.py')
        prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare)
        config = prepare.prepare(tmp_path / 'demo') / 'service.json'
        document = json.loads(config.read_text(encoding='utf-8'))
        cache = Path('.runtime/embeddings').resolve()
        document['embeddings_cache'] = str(cache)
        config.write_text(json.dumps(document), encoding='utf-8')
        service = ServiceConfig.model_validate(document)
        tenant = service.tokens[0].identity.tenant_id
        users = [grant.identity.user_id for grant in service.tokens]
        documents = json.loads(
            Path('examples/synthetic/perception-v1/knowledge.json').read_text(
                encoding='utf-8'))['documents']
        documents.append({
            'data_origin': 'SYNTHETIC',
            'doc_id': 'p13-preflight-hot-work',
            'version': 1,
            'title': '合成动火作业前依据',
            'source': 'synthetic-p13-policy/preflight',
            'valid_from': '2026-09-22T03:00:00Z',
            'valid_until': '2026-09-23T00:00:00Z',
            'allowed_users': users,
            'paragraphs': [
                'SYNTHETIC：作业前先核对已确认作业人员的焊接资质、当前区域状态和适用规程。'
                '安全人员必须明确选择实际采用的引用；材料核查完成不代表作业批准或开工授权。'
            ],
        })

        async def seed():
            embeddings = await LocalEmbeddings.create(cache)
            store = KnowledgeStore(dsn, embeddings, clock=lambda: service.as_of)
            await store.initialize()
            owner = Identity(tenant_id=tenant, user_id=users[0])
            for item in documents:
                await store.ingest(owner, item | {'allowed_users': users})

        asyncio.run(seed(), loop_factory=asyncio.SelectorEventLoop)
    module = preflight_verifier()
    report = module.verify(Path(wheel), Path(config), dsn)
    assert report['status'] == 'passed'
    assert len(set(report['process_ids'])) == 3
    assert report['application_version'] == 5
    assert report['precheck_blocked_worker'] == 'worker-p13-alert'
    assert report['precheck_blocked_area'] == 'area-p13-restricted'
    assert report['precheck_ready_binding_revision'] == 2
    assert report['event_review']['binding_revision'] == 2
    assert report['event_review']['alarm_state'] == 'active'
    assert report['event_review']['currentness'] == 'current'
    assert all(str(Path(wheel).resolve()) in value for value in report['module_files'])
    assert report['cwd_outside_source']
    assert report['real_model_requests'] == 0
    assert len(report['process_lifecycle']) == 3
    assert all(row['pid'] == row['launched_pid'] and row['exit_verified'] and row['port_closed']
               for row in report['process_lifecycle'])
    assert report['temporary_directory_removed']
    assert 1 <= report['directory_cleanup_attempts'] <= 40
