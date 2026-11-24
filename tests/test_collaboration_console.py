"""Role UI contract, reconnect inbox semantics and private demo configuration."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_collaboration_api import clients, command, send, start
from test_events_postgres import dsn, run  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.postgres
def test_console_role_todos_and_reconnect_event_dedup(dsn):  # noqa: F811
    async def scenario():
        async with clients(dsn) as (sessions, _, _):
            a, b = sessions[:2]
            task = (await start(a))['task_id']
            await send(a, task, 'submit', command(reviewer_user_id='reviewer'))
            inbox = (await b.get('/collaboration/notifications?after=0&limit=1')).json()
            assert len(inbox['items']) == 1
            cursor = inbox['next_cursor']
            next_page = (await b.get(f'/collaboration/notifications?after={cursor}')).json()
            assert next_page['items'] == []
            replay = (await b.get('/collaboration/notifications?after=0')).json()
            assert replay['items'] == inbox['items']
            assert len((await b.get('/collaboration/applications')).json()['items']) == 1
            page = (await a.get('/console')).text
            assert 'id="application-list"' in page
            assert 'id="business-inbox"' in page
            assert '材料核查完成≠批准作业' in page
            script = (await a.get('/console/assets/app.js')).text
            assert 'next_cursor' in script and 'event_id' in script
            assert 'resetIdentityState' in script
            api = (await a.get('/console/assets/api.js')).text
            assert 'connectionEpoch' in api and 'controllers' in api
    run(scenario())


def test_demo_script_writes_new_distinct_private_configs_without_printing_tokens(tmp_path):
    script = ROOT / 'scripts/prepare_collaboration_demo.py'
    assert script.is_file(), '双角色私密配置准备脚本尚未实现'
    response = subprocess.run([sys.executable, str(script), '--output', str(tmp_path / 'demo')],
                              capture_output=True, text=True, encoding='utf-8')
    assert response.returncode == 0, response.stderr
    output = tmp_path / 'demo'
    configs = [json.loads((output / f'{name}.json').read_text(encoding='utf-8'))
               for name in ('service', 'applicant', 'safety-manager')]
    service, applicant, reviewer = configs
    assert service['model_mode'] == 'scripted_double'
    a, b = applicant['tokens'][0], reviewer['tokens'][0]
    assert a['identity'] != b['identity'] and a['token'] != b['token']
    assert {a['token'], b['token']} == {g['token'] for g in service['tokens']}
    assert all(g['token'] not in response.stdout + response.stderr for g in (a, b))
    before = (output / 'service.json').read_bytes()
    second = subprocess.run([sys.executable, str(script), '--output', str(output)],
                            capture_output=True, text=True)
    assert second.returncode != 0 and (output / 'service.json').read_bytes() == before


def test_connection_switch_discards_late_requests_and_aborts_streams(tmp_path):
    source = ROOT / 'src/anlan/interfaces/console/assets/api.js'
    module = tmp_path / 'api.mjs'
    module.write_bytes(source.read_bytes())
    harness = tmp_path / 'switch.mjs'
    harness.write_text('''
import assert from 'node:assert/strict';
import {connectToken, disconnectToken, request, subscribeSnapshot} from './api.mjs';
let release, requestSignal, streamSignal, snapshots = 0;
connectToken('first-identity');
globalThis.fetch = async (_url, options) => {
  requestSignal = options.signal;
  return await new Promise(resolve => {release = () => resolve({ok:true,
    json:async () => ({private:'FIRST-IDENTITY-RESPONSE'})});});
};
const pending = request('/console/api/info').catch(error => error);
connectToken('second-identity');
assert.equal(requestSignal.aborted, true);
release();
assert.equal((await pending).stale, true);
globalThis.fetch = async (_url, options) => {
  streamSignal = options.signal;
  return {ok:true, body:{getReader:() => ({read:async () => await new Promise(resolve => {
    release = () => resolve({done:false, value:new TextEncoder().encode(
      'event: snapshot\\ndata: {"private":"SECOND-IDENTITY"}\\n\\n')});
  })})}};
};
const stream = subscribeSnapshot('/conversations/second/stream', {
  onSnapshot:() => snapshots++, onError:() => {throw Error('stale error callback');}});
await new Promise(resolve => setImmediate(resolve));
disconnectToken();
assert.equal(streamSignal.aborted, true);
release(); await stream;
assert.equal(snapshots, 0);
console.log('identity request/stream isolation passed');
''', encoding='utf-8')
    result = subprocess.run([shutil.which('node') or 'node', str(harness)],
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


def test_unchanged_poll_preserves_interactive_cards_and_form_drafts(tmp_path):
    harness = tmp_path / 'poll.mjs'
    harness.write_text('''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const value = {conversation_id:'own', revision:1, status:'pending_confirmation', messages:[]};
let response = structuredClone(value);
const elements = new Map();
let subscriptions = 0;
const context = {renderCount:0, clearTimeout:() => {}, AbortController,
  subscribeSnapshot:() => {subscriptions++;},
  request:async () => structuredClone(response),
  document:{querySelectorAll:() => [], getElementById:id => {
    if (!elements.has(id)) elements.set(id, {addEventListener(){}, replaceChildren(){}});
    return elements.get(id);
  }}};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], 'utf8').replace(/^import .*\\r?\\n/, '');
vm.runInContext(source + `
globalThis.subject = {state, refreshConversation, resetIdentityState, startStream, loadEvents};
renderSnapshot = () => {globalThis.renderCount++;};
loadEvents = async () => {};
renderEvents = renderReview = () => {};
`, context);
context.subject.state.snapshot = structuredClone(value);
await context.subject.refreshConversation({quiet:true});
assert.equal(context.renderCount, 0, 'unchanged poll replaced confirmation/form DOM');
response.revision = 2;
await context.subject.refreshConversation({quiet:true});
assert.equal(context.renderCount, 1, 'changed snapshot must refresh the UI');
let aborted = 0;
const state = context.subject.state;
state.stream = {abort:() => aborted++}; state.streamId = 'private-stream';
state.notificationCursor = 123; state.notifications.set('private-event', {});
state.businessDrafts.set('private-task:request_changes', 'PRIVATE-DRAFT');
state.applications = [{task_id:'private-task'}];
context.subject.resetIdentityState();
assert.equal(aborted, 1);
assert.equal(state.streamId, null); assert.equal(state.stream, null);
assert.equal(state.snapshot, null); assert.equal(state.info, null);
assert.equal(state.businessDrafts.size, 0); assert.equal(state.notificationCursor, 0);
assert.equal(state.notifications.size, 0); assert.equal(state.applications.length, 0);
assert.equal(elements.get('message-input').value, '');
state.info = {collaboration_role:'safety_manager'};
context.subject.startStream('own');
assert.equal(subscriptions, 0, 'shared UI uses its bounded poll, not a competing fast SSE reader');
let release;
context.request = async () => await new Promise(resolve => {release = resolve;});
state.snapshot = structuredClone(value);
const pendingRefresh = context.subject.refreshConversation({quiet:true});
state.snapshot = {...value, conversation_id:'new-selection'};
release(structuredClone(value)); await pendingRefresh;
assert.equal(state.snapshot.conversation_id, 'new-selection',
  'late poll reverted conversation selection');
state.snapshot.task_projection = {task_id:'old-task'};
state.events = [];
const pendingEvents = context.subject.loadEvents();
state.snapshot.task_projection = {task_id:'new-task'};
release({items:[{receipt_id:'old-task-event'}]}); await pendingEvents;
assert.equal(state.events.length, 0, 'late event read leaked into the newly selected task panel');
state.event = {receipt_id:'selected-event'};
state.review = {review_id:'selected-review', currentness:'current'};
context.request = async path => path.startsWith('/reviews/') ? {
  review_id:'selected-review', currentness:'stale_material'
} : path.includes('/events/selected-event/reviews') ? {
  items:[{review_id:'selected-review'}]
} : {items:[{receipt_id:'selected-event'}]};
await context.subject.loadEvents();
assert.equal(state.review.currentness, 'stale_material',
  'selected review did not refresh after the material changed');
''', encoding='utf-8')
    result = subprocess.run([shutil.which('node') or 'node', str(harness),
                             str(ROOT / 'src/anlan/interfaces/console/assets/app.js')],
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
