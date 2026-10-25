"""Local-only scripted wheel Gate, with four actual isolated application processes.

Never accepts a remote URL or live model configuration. Fault injection is confined
to the subprocess harness: exit immediately after the real PG command commits.
"""

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import zipfile
from ipaddress import ip_address
from pathlib import Path
from uuid import uuid4

import httpx
from psycopg import Error as PsycopgError
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'package_layout', ROOT / 'scripts/verify_package_layout.py')
_package_layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_package_layout)


def verify_resources(archive, root):
    resources = _package_layout.verify_resources(archive, root)
    for path in sorted((root / 'src/anlan/interfaces/console/assets').rglob('*')):
        if path.is_file():
            name = path.relative_to(root / 'src').as_posix()
            content = archive.read(name)
            if content != path.read_bytes():
                raise ValueError('Wheel console resource differs from source')
            resources.append({'path': name, 'sha256': hashlib.sha256(content).hexdigest()})
    return resources

LAUNCH = '''
import asyncio,json,os,sys
from contextlib import asynccontextmanager
from pathlib import Path
sys.path.insert(0,sys.argv[6])
sys.path.insert(0,sys.argv[1])
import anlan,uvicorn
from anlan.interfaces.api import create_app
from anlan.interfaces.service_config import ServiceConfig
from anlan.collaboration.service import CollaborationService
if sys.argv[4] == 'crash_after_commit':
    original = CollaborationService.execute
    async def crash(self,*args,**kwargs):
        await original(self,*args,**kwargs)
        os._exit(91)
    CollaborationService.execute = crash
app=create_app(os.environ['ANLAN_DATABASE_URL'],ServiceConfig.from_file(Path(sys.argv[2])))
@app.get('/_release_harness_ready')
async def harness_ready():
    return {'pid':os.getpid(),'generation':sys.argv[7]}
original_lifespan=app.router.lifespan_context
@asynccontextmanager
async def lifespan(app):
    async with original_lifespan(app):
        Path(sys.argv[5]).write_text(json.dumps({'module_file':anlan.__file__,
            'knowledge':type(app.state.knowledge).__name__,'pid':os.getpid(),
            'generation':sys.argv[7]}))
        yield
app.router.lifespan_context=lifespan
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=int(sys.argv[3]),
    access_log=False,log_level='critical'))
asyncio.run(server.serve(),loop_factory=asyncio.SelectorEventLoop)
'''


def validate_config(config):
    if config.get('model_mode') != 'scripted_double':
        raise ValueError('Gate requires explicit scripted_double mode')
    applicants = [g for g in config['tokens'] if g.get('collaboration_role') == 'applicant']
    managers = [g for g in config['tokens'] if g.get('collaboration_role') == 'safety_manager']
    for a in applicants:
        for b in managers:
            if (a['identity']['tenant_id'] == b['identity']['tenant_id']
                    and a['identity']['user_id'] != b['identity']['user_id']):
                return a, b
    raise ValueError('Gate needs distinct same-tenant participants')


def new_evidence_directory(path):
    path.mkdir(parents=True, exist_ok=False)
    return path


TARGET_ERROR = ('Gate requires one explicit loopback PostgreSQL target '
                'without service or inherited PG settings')


def loopback_dsn(dsn, *, environment=None):
    """Pure parsing only: reject implicit overrides and pin the actual libpq address.

    This harness supports one TCP target, not service files, sockets or multihost.
    Reject nonempty PG* settings rather than silently interpreting another target;
    the launch boundary also removes every PG* variable from its environment.
    """
    environment = os.environ if environment is None else environment
    if any(key.upper().startswith('PG') and value for key, value in environment.items()):
        raise ValueError(TARGET_ERROR)
    try:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError
        params = conninfo_to_dict(dsn)
        if 'service' in params:
            raise ValueError
        host = params.get('host', '')
        if host.lower() == 'localhost':
            host, address = 'localhost', '127.0.0.1'
        else:
            address = ip_address(host)
            if not address.is_loopback or '%' in host:
                raise ValueError
            host, address = address.compressed, address.compressed
        if 'hostaddr' in params:
            target = ip_address(params['hostaddr'])
            if not target.is_loopback or '%' in params['hostaddr']:
                raise ValueError
            address = target.compressed
        port = params.get('port', '5432')
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError
        return make_conninfo(**(params | {'host': host, 'hostaddr': address, 'port': port}))
    except (PsycopgError, TypeError, ValueError):
        # libpq parser errors may contain the original DSN, so suppress their chain.
        raise ValueError(TARGET_ERROR) from None


def windows_listener_ports():
    """Read both Windows TCP listener tables; no connection timeout inference."""
    import ctypes
    from ctypes import wintypes

    query = ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG), wintypes.BOOL,
                      wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    query.restype = wintypes.DWORD
    ports = set()
    # OWNER_PID_LISTENER rows: IPv4 is 24 bytes (port offset 8), IPv6 56 (offset 20).
    for family, row_size, port_offset in ((2, 24, 8), (23, 56, 20)):
        size = wintypes.ULONG()
        if query(None, ctypes.byref(size), False, family, 3, 0) not in {0, 122}:
            raise OSError('Cannot query local listener table size')
        size.value += 4096
        table = ctypes.create_string_buffer(size.value)
        if query(table, ctypes.byref(size), False, family, 3, 0) != 0:
            raise OSError('Cannot query local listener table')
        count = int.from_bytes(table.raw[:4], 'little')
        if 4 + count * row_size > len(table):
            raise OSError('Invalid local listener table size')
        for index in range(count):
            offset = 4 + index * row_size + port_offset
            value = int.from_bytes(table.raw[offset:offset + 4], 'little')
            ports.add(socket.ntohs(value & 65535))
    return ports


def socket_listening(port):
    with socket.socket() as connection:
        connection.settimeout(.1)
        result = connection.connect_ex(('127.0.0.1', port))
    if result in {errno.ECONNREFUSED, 10061}:
        return False
    if result != 0:
        raise OSError('Cannot determine local listener state')
    return True


def port_closed(port):
    """Check the local control-plane port only; never retry a business/model request."""
    deadline = time.monotonic() + 2
    while True:
        try:
            listening = (port in windows_listener_ports() if os.name == 'nt'
                         else socket_listening(port))
            if not listening:
                return True
        except OSError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(.05)


def cleanup_directory(directory, *, processes_stopped=False):
    """Only delete this harness's owned temp root, after verified process/port exit."""
    if not processes_stopped:
        raise RuntimeError('Cannot clean directory before tracked process exit')
    directory = Path(directory)
    if (directory.is_symlink() or directory.is_junction()
            or directory.resolve().parent != Path(tempfile.gettempdir()).resolve()
            or not directory.name.startswith('anlan-b4-wheel-')):
        raise ValueError('Cleanup target is not an owned wheel temporary directory')
    for attempt in range(40):
        try:
            shutil.rmtree(directory)
            return attempt + 1
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) != 32 or attempt == 39:
                raise
            time.sleep(.05)


class WheelServer:
    def __init__(self, wheel, config, dsn, directory, port):
        self.wheel, self.config, self.dsn = wheel, config, dsn
        self.directory, self.port = directory, port
        self.process = None
        self.history = []

    def start(self, mode='normal'):
        environment = dict(os.environ)
        dsn = loopback_dsn(self.dsn, environment=environment)
        if self.process is not None and not self.history[-1].get('exit_verified'):
            raise RuntimeError('Stop the tracked process before starting another generation')
        index = len(self.history)
        marker = self.directory / f'provenance-{index}.json'
        generation = uuid4().hex
        executable = getattr(sys, '_base_executable', None)
        if not executable or not Path(executable).is_file():
            raise RuntimeError('Cannot identify the direct Python runtime')
        env = {k: v for k, v in environment.items() if not k.upper().startswith('PG')
               and k.upper() not in {'PYTHONPATH', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'}}
        env.update(ANLAN_DATABASE_URL=dsn, ANLAN_TEST_DATABASE_URL=dsn,
                   PYTHONIOENCODING='utf-8')
        self.process = subprocess.Popen(
            [executable, '-I', '-c', LAUNCH, str(self.wheel), str(self.config),
             str(self.port), mode, str(marker), sysconfig.get_path('purelib'), generation],
            cwd=self.directory, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.history.append({'pid': self.process.pid, 'launched_pid': self.process.pid,
                             'port': self.port})
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Wheel process exited before readiness')
            try:
                ready = httpx.get(f'http://127.0.0.1:{self.port}/_release_harness_ready',
                                  trust_env=False, timeout=1)
                if ready.status_code == 200 and ready.json().get('generation') == generation:
                    provenance = json.loads(marker.read_text())
                    if (ready.json().get('pid') != self.process.pid
                            or provenance['pid'] != self.process.pid
                            or provenance['generation'] != generation):
                        raise RuntimeError('Serving PID does not match the launched Python process')
                    assert str(self.wheel) in provenance['module_file']
                    self.history[-1].update({k: v for k, v in provenance.items()
                                             if k != 'generation'})
                    return
            except (httpx.HTTPError, OSError):
                pass
            time.sleep(0.1)
        raise RuntimeError('Wheel readiness deadline exceeded')

    def stop(self):
        if self.process is None or self.history[-1].get('exit_verified'):
            return
        if self.process.poll() is None:
            self.process.terminate()
        try:
            exit_code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            exit_code = self.process.wait(timeout=10)
        closed = port_closed(self.port)
        self.history[-1].update(exit_code=exit_code, port_closed=closed, exit_verified=closed)
        if not closed:
            raise RuntimeError('Tracked process exited but its local port remains occupied')


def verify(wheel, config_path, dsn):
    dsn = loopback_dsn(dsn)
    wheel, config_path = wheel.resolve(), config_path.resolve()
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    applicant, manager = validate_config(config)
    with zipfile.ZipFile(wheel) as archive:
        resources = verify_resources(archive, ROOT)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    report = {'status': 'running', 'model_mode': 'scripted_double',
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'database_target': {'kind': 'single_explicit_loopback', 'address_pinned': True,
                  'pg_environment': 'nonempty_rejected_all_removed',
                  'validation_boundaries': ['verify', 'process_start']},
              'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
              'resources': resources, 'credentials_recorded': False}
    directory = Path(tempfile.mkdtemp(prefix='anlan-b4-wheel-')).resolve()
    server = None
    try:
        report['cwd_outside_source'] = not directory.is_relative_to(ROOT)
        server = WheelServer(wheel, config_path, dsn, directory, port)
        base = f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=base, trust_env=False, timeout=30,
                          headers={'Authorization': 'Bearer ' + applicant['token']}) as a, \
             httpx.Client(base_url=base, trust_env=False, timeout=30,
                          headers={'Authorization': 'Bearer ' + manager['token']}) as b:
            def request(client, method, path, payload=None, status=200):
                response = client.request(method, path, json=payload)
                if response.status_code != status:
                    raise AssertionError(f'Gate HTTP {method} {path}: {response.status_code}')
                return response.json()

            def post(client, path, payload):
                return request(client, 'POST', path, payload)

            def read(client, path):
                return request(client, 'GET', path)

            def say(client, conv, text):
                return post(client, f"/conversations/{conv['conversation_id']}/messages", {
                    'request_id': uuid4().hex, 'expected_revision': conv['revision'], 'text': text})

            def card(client, conv, intent, payload):
                path = f"/conversations/{conv['conversation_id']}/collaboration-candidates"
                return post(client, path,
                            {'request_id': uuid4().hex, 'expected_revision': conv['revision'],
                             'intent': intent, 'collaboration': payload})

            try:
                server.start()
                fields = {key: value for key, value in zip(
                    ('work_location_description', 'work_object_description',
                     'work_method_description', 'attachment_description'),
                    ('SYNTHETIC台架', 'SYNTHETIC试件', '焊接演示', 'SYNTHETIC示意图'))}
                task = post(a, '/tasks', {'request_id': uuid4().hex, 'fields': fields})['task_id']
                ca = post(a, '/conversations', {'request_id': uuid4().hex})
                ca = post(a, f"/conversations/{ca['conversation_id']}/task", {
                    'task_id': task, 'expected_revision': ca['revision']})
                ca = card(a, ca, 'submit_application', {
                    'reviewer_user_id': manager['identity']['user_id']})
                frozen = ca['pending_intent']['collaboration']
                assert frozen['payload']['expected_application_version'] == 1
                assert frozen['payload']['expected_material_revision'] == 1
                server.stop()
                server.start('crash_after_commit')
                persisted = read(a, f"/conversations/{ca['conversation_id']}")
                assert persisted['pending_intent']['collaboration'] == frozen
                confirmation = {'request_id': uuid4().hex,
                                'expected_revision': ca['revision'], 'text': '确认'}
                path = f"/conversations/{ca['conversation_id']}/messages"
                try:
                    a.post(path, json=confirmation)
                    raise AssertionError('Fault injection did not terminate process')
                except (httpx.RemoteProtocolError, httpx.ReadError):
                    pass
                report['crash_exit_code'] = server.process.wait(timeout=10)
                assert report['crash_exit_code'] == 91
                server.stop()
                server.start()
                ca = post(a, path, confirmation)
                assert post(a, path, confirmation) == ca
                shared_path = f'/collaboration/applications/{task}'
                shared = read(a, shared_path)
                assert shared['application']['version'] == 2
                report['submit_event_count'] = sum(
                    e['action'] == 'submit' for e in shared['events'])
                inbox = read(b, '/collaboration/notifications')
                report['submit_notification_count'] = sum(
                    n['event']['task_id'] == task and n['event']['action'] == 'submit'
                    for n in inbox['items'])
                assert report['submit_event_count'] == report['submit_notification_count'] == 1
                cb = post(b, '/conversations', {'request_id': uuid4().hex})
                cb = post(b, f"/conversations/{cb['conversation_id']}/task", {
                    'task_id': task, 'expected_revision': cb['revision']})
                cb = card(b, cb, 'request_changes', {'questions': ['明确SYNTHETIC台架东侧点位']})
                cb = say(b, cb, '确认')
                post(a, f'/tasks/{task}/revise', {'request_id': uuid4().hex,
                    'expected_revision': 1,
                    'fields': {'work_location_description': 'SYNTHETIC台架东侧1号点位'}})
                ca = read(a, f"/conversations/{ca['conversation_id']}")
                ca = card(a, ca, 'resubmit_application', {'reply': '已补充东侧1号点位'})
                ca = say(a, ca, '确认')
                cb = read(b, f"/conversations/{cb['conversation_id']}")
                cb = card(b, cb, 'complete_material_review', {
                    'conclusion': '人工核对第2版材料齐备'})
                frozen_complete = cb['pending_intent']['collaboration']
                server.stop()
                server.start()
                cb = read(b, f"/conversations/{cb['conversation_id']}")
                assert cb['pending_intent']['collaboration'] == frozen_complete
                cb = say(b, cb, '确认')
                for client, conv in ((a, ca), (b, cb)):
                    restored = read(client, f"/conversations/{conv['conversation_id']}")
                    app = restored['task_projection']['collaboration']['application']
                    assert restored['active_task_id'] == task
                    assert app['status'] == 'review_completed'
                    assert app['version'] == 5 and app['completed_material_revision'] == 2
                report.update(status='passed', task_id=task, application_version=5,
                    completed_material_revision=2, applicant_conversation=ca['conversation_id'],
                    reviewer_conversation=cb['conversation_id'],
                    process_ids=[p['pid'] for p in server.history],
                    module_files=[p['module_file'] for p in server.history],
                    knowledge_compositions=[p['knowledge'] for p in server.history])
            finally:
                server.stop()
    finally:
        stopped = server is None or all(row.get('exit_verified') for row in server.history)
        report['directory_cleanup_attempts'] = cleanup_directory(
            directory, processes_stopped=stopped)
    report['process_lifecycle'] = server.history
    report['temporary_directory_removed'] = not directory.exists()
    if not report['temporary_directory_removed']:
        raise RuntimeError('Owned wheel temporary directory was not removed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new evidence file')
    dsn = os.environ['ANLAN_TEST_DATABASE_URL']
    try:
        report = verify(args.wheel, args.config, dsn)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({'status': report['status'], 'processes': len(report['process_ids']),
                      'credentials_recorded': False}))


if __name__ == '__main__':
    main()
