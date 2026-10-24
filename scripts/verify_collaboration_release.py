"""Local-only scripted wheel Gate, with four actual isolated application processes.

Never accepts a remote URL or live model configuration. Fault injection is confined
to the subprocess harness: exit immediately after the real PG command commits.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx

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
original_lifespan=app.router.lifespan_context
@asynccontextmanager
async def lifespan(app):
    async with original_lifespan(app):
        Path(sys.argv[5]).write_text(json.dumps({'module_file':anlan.__file__,
            'knowledge':type(app.state.knowledge).__name__,'pid':os.getpid()}))
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


class WheelServer:
    def __init__(self, wheel, config, dsn, directory, port):
        self.wheel, self.config, self.dsn = wheel, config, dsn
        self.directory, self.port = directory, port
        self.process = None
        self.history = []

    def start(self, mode='normal'):
        index = len(self.history)
        marker = self.directory / f'provenance-{index}.json'
        env = {k: v for k, v in os.environ.items() if k not in {
            'PYTHONPATH', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'}}
        env.update(ANLAN_DATABASE_URL=self.dsn, PYTHONIOENCODING='utf-8')
        self.process = subprocess.Popen(
            [sys.executable, '-I', '-c', LAUNCH, str(self.wheel), str(self.config),
             str(self.port), mode, str(marker)], cwd=self.directory, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.history.append({'pid': self.process.pid})
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Wheel process exited before readiness')
            try:
                if httpx.get(f'http://127.0.0.1:{self.port}/healthz',
                             trust_env=False, timeout=1).status_code == 200:
                    provenance = json.loads(marker.read_text())
                    assert str(self.wheel) in provenance['module_file']
                    self.history[-1].update(provenance)
                    return
            except (httpx.HTTPError, OSError):
                pass
            time.sleep(0.1)
        raise RuntimeError('Wheel readiness deadline exceeded')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


def verify(wheel, config_path, dsn):
    wheel, config_path = wheel.resolve(), config_path.resolve()
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    applicant, manager = validate_config(config)
    with zipfile.ZipFile(wheel) as archive:
        resources = verify_resources(archive, ROOT)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    report = {'status': 'running', 'model_mode': 'scripted_double',
              'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
              'resources': resources, 'credentials_recorded': False}
    with tempfile.TemporaryDirectory(prefix='anlan-b4-wheel-') as temporary:
        directory = Path(temporary)
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
    # Never allow this verification harness to connect to a remote database.
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(dsn).get('host') not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('Gate requires explicit loopback PostgreSQL')
    report = verify(args.wheel, args.config, dsn)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({'status': report['status'], 'processes': len(report['process_ids']),
                      'credentials_recorded': False}))


if __name__ == '__main__':
    main()
