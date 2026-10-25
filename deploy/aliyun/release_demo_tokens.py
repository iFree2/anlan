"""Scoped synthetic credential release; never prints credentials or restores a DB."""
import importlib.util
import json
import os
import shutil
import sys
import zipfile

spec = importlib.util.spec_from_file_location('p12_release',
    '/opt/anlan2/release-collaboration-20261025.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
BASE = r.NEW
NEW = r.ROOT / 'releases/p12-demo-tokens-20261025'
BACKUP = r.SHARED / 'before-p12-demo-tokens-20261025'
SHA = 'b2e62fcb568d4cca61767eba8c78893de3bce91749f2969683d09b2cfcce8b5f'
PATHS = [r.SHARED / 'console.json', r.PRIVATE / 'service.json',
         r.PRIVATE / 'applicant.json', r.PRIVATE / 'safety-manager.json']
r.NEW = NEW  # Existing rollback remains maintenance; forward targets this compatible build.

def emit(document):
    print(json.dumps(document))

def write_config(path, value):
    temporary = path.with_name(path.name + '.short-token-pending')
    r.require(not temporary.exists(), 'Pending config exists; inspect first')
    try:
        r.private_json(temporary, value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def switch(target):
    r.require(target in (BASE, NEW), 'Unexpected release target')
    temporary = r.ROOT / 'current.short-token-pending'
    r.require(not temporary.exists() and not temporary.is_symlink(), 'Pending release exists')
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, r.ROOT / 'current')
    finally:
        temporary.unlink(missing_ok=True)

def preflight():
    r.require((r.ROOT / 'current').resolve() == BASE, 'Unexpected active release')
    r.require(not BACKUP.exists() and not NEW.exists(), 'Already prepared; inspect first')
    before = r.snapshot()
    r.require_quiescent(before['pending'])
    original = json.loads(PATHS[0].read_text())
    r.wait_ready(original)
    BACKUP.mkdir(mode=0o700)
    for index, path in enumerate(PATHS):
        destination = BACKUP / (str(index) + '.json')
        shutil.copy2(path, destination)
        destination.chmod(0o600)
    r.private_json(BACKUP / 'before.json', before)
    r.private_json(BACKUP / 'recovery.json', {'base':str(BASE), 'new':str(NEW),
        'maintenance':str(r.MAINTENANCE), 'policy':'Config/application only; never restore DB'})
    emit({'status':'preflight_ok', 'backup':str(BACKUP), 'ledger':before['ledger'],
          'current':str(BASE)})

def prepare():
    r.require((r.ROOT / 'current').resolve() == BASE, 'Unexpected active release')
    r.require(not NEW.exists(), 'Release already exists; inspect first')
    request = BACKUP / 'request.json'
    request.chmod(0o600)
    requested = json.loads(request.read_text())
    r.require(set(requested) == {'applicant','safety_manager'}, 'Two exact roles required')
    r.require(all(isinstance(value, str) and value for value in requested.values()),
              'Nonempty credentials required')
    r.require(len(set(requested.values())) == 2, 'Distinct credentials required')
    original = json.loads((BACKUP / '0.json').read_text())
    config = json.loads(json.dumps(original))
    changed = []
    for grant in config['tokens']:
        role = grant.get('collaboration_role')
        if role in requested:
            grant['token'] = requested[role]
            grant['demo_short_token'] = True
            changed.append(role)
    r.require(sorted(changed) == ['applicant','safety_manager'], 'Unexpected role mapping')
    wheel = BACKUP / 'anlan-0.1.0-py3-none-any.whl'
    r.validate_wheel(wheel, SHA)
    NEW.mkdir(mode=0o755)
    (NEW / 'venv').symlink_to((BASE / 'venv').resolve(), target_is_directory=True)
    (NEW / 'examples').symlink_to((BASE / 'examples').resolve(), target_is_directory=True)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(NEW / 'app')
    shutil.copy2(wheel, NEW / wheel.name)
    r.private_json(BACKUP / 'new-service.json', config)
    probe = r.environment() | {'PYTHONPATH':str(NEW / 'app')}
    r.command(str(NEW / 'venv/bin/python'), '-c',
        "from anlan.interfaces.service_config import ServiceConfig; "
        "ServiceConfig.from_file('/opt/anlan2/shared/before-p12-demo-tokens-20261025/new-service.json')",
        env=probe)
    emit({'status':'prepared', 'new_release':str(NEW), 'wheel_sha256':SHA,
          'changed_roles':changed, 'new_model_requests':0})

def activate():
    r.require((r.ROOT / 'current').resolve() == BASE, 'Unexpected active release')
    originals = [json.loads((BACKUP / (str(i) + '.json')).read_text()) for i in range(4)]
    r.require(all(json.loads(path.read_text()) == document
                  for path, document in zip(PATHS, originals)), 'Configuration changed')
    new_config = json.loads((BACKUP / 'new-service.json').read_text())
    new_documents = [new_config, new_config]
    for role in ('applicant','safety_manager'):
        grant = next(g for g in new_config['tokens'] if g.get('collaboration_role') == role)
        new_documents.append({'schema_version':'local-service-v1', 'tokens':[grant]})
    r.require_quiescent(r.snapshot()['pending'])
    try:
        r.command('systemctl', 'stop', 'anlan2-console')
        before = r.snapshot()
        r.require_quiescent(before['pending'])
        for path, document in zip(PATHS, new_documents):
            write_config(path, document)
        switch(NEW)
        r.command('systemctl', 'start', 'anlan2-console')
        infos = r.wait_ready(new_config)
        old_tokens = [g['token'] for g in originals[0]['tokens']
                      if g.get('collaboration_role') in ('applicant','safety_manager')]
        r.require(all(r.request('/console/api/info', token)[0] == 401 for token in old_tokens),
                  'Old role credential still accepted')
        after = r.snapshot()
        r.require(before['rows'] == after['rows'], 'Business rows changed')
        r.require(before['ledger'] == after['ledger'], 'Budget changed')
    except Exception:
        r.command('systemctl', 'stop', 'anlan2-console')
        for path, document in zip(PATHS, originals):
            write_config(path, document)
        switch(BASE)
        r.command('systemctl', 'start', 'anlan2-console')
        r.wait_ready(originals[0])
        raise RuntimeError('Activation failed; original P12 configs/application restored') from None
    (BACKUP / 'request.json').unlink()
    report = {'status':'activated', 'current':str(NEW), 'backup':str(BACKUP),
              'wheel_sha256':SHA, 'business_rows_unchanged':True, 'ledger_unchanged':True,
              'ledger':after['ledger'], 'pending':after['pending'], 'old_role_tokens_http':401,
              'new_role_credentials_verified':True, 'legacy_token_preserved':True,
              'identity_roles_preserved':True, 'new_model_requests':0,
              'roles':[{'role':i.get('collaboration_role'),
                        'demo_short_token':i.get('demo_short_token')} for i in infos]}
    r.private_json(BACKUP / 'activated.json', report)
    emit(report)

try:
    action = sys.argv[1]
    if action == 'preflight':
        preflight()
    elif action == 'prepare':
        prepare()
    elif action == 'activate':
        activate()
    elif action == 'rollback':
        emit(r.rollback())
    elif action == 'forward':
        emit(r.forward())
    else:
        raise RuntimeError('Unsupported action')
except Exception as exc:
    emit({'status':'failed', 'error_type':type(exc).__name__, 'details':'Private output hidden'})
    raise SystemExit(1)
