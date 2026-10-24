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
const source = fs.readFileSync(process.argv[2], 'utf8').replace(/^import .*\\n/, '');
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
    import json
    import os
    import subprocess

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
        document['embeddings_cache'] = str(Path('.runtime/embeddings').resolve())
        config.write_text(json.dumps(document), encoding='utf-8')
    module = verifier()
    report = module.verify(Path(wheel), Path(config), dsn)
    assert report['status'] == 'passed'
    assert len(set(report['process_ids'])) == 4
    assert report['crash_exit_code'] == 91
    assert report['application_version'] == 5
    assert report['completed_material_revision'] == 2
    assert report['applicant_conversation'] != report['reviewer_conversation']
    assert all(str(Path(wheel).resolve()) in value for value in report['module_files'])
    assert report['cwd_outside_source']
    assert report['submit_event_count'] == report['submit_notification_count'] == 1
