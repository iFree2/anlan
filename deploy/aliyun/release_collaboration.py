"""Scoped P12 release and fail-closed maintenance recovery; never restore a ledger."""

import argparse
import copy
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from uuid import uuid4

ROOT = Path('/opt/anlan2')
OLD = ROOT / 'releases/p11-conversation-verified-20261022'
NEW = ROOT / 'releases/p12-collaboration-20261025'
MAINTENANCE = ROOT / 'releases/p12-maintenance-20261025'
SHARED = ROOT / 'shared'
BACKUP = SHARED / 'before-p12-collaboration-20261025'
PRIVATE = SHARED / 'p12-collaboration-20261025'
AUTH = '20260920-long-term-v1'

# This module is the entire fallback application: no legacy handlers or database imports.
MAINTENANCE_SOURCE = '''import argparse
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

def create_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    @app.get('/health/ready')
    async def health():
        return {'status': 'maintenance', 'writable': False}
    @app.api_route('/{path:path}', methods=['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'])
    async def maintenance(path):
        return JSONResponse({'mode': 'maintenance', 'writable': False,
                             'detail': 'Application maintenance; records are preserved.'},
                            status_code=503, headers={'Retry-After': '300'})
    return app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--port', type=int, default=8018)
    parser.add_argument('--root-path', default='')
    args = parser.parse_args()
    uvicorn.run(create_app(), host='127.0.0.1', port=args.port, root_path=args.root_path,
                access_log=False, log_level='warning')
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(*args, env=None, timeout=180):
    result = subprocess.run(args, capture_output=True, env=env, timeout=timeout)
    require(result.returncode == 0, 'Management command failed; private output hidden')
    return result.stdout.decode().strip()


def environment():
    env = os.environ.copy()
    for line in (SHARED / 'app.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, sep, value = line.partition('=')
            if sep:
                env[key] = shlex.split(value)[0] if value else ''
    return env


def live_plan(ledger):
    require((ledger['total_limit'], ledger['conversation_limit'],
             ledger['materials_events_limit']) == (100, 30, 10),
            'Unexpected authorization limits')
    require(ledger['total'] + 10 <= 100 and ledger['conversation'] + 7 <= 30
            and ledger['materials_events'] + 3 <= 10, 'Insufficient live budget')
    return {'conversation': 7, 'materials': 2, 'event': 1}


def require_quiescent(pending):
    require(not any(pending.values()), 'Unfinished operations; inspect without replay')


def dual_config(old, references, facts):
    config = copy.deepcopy(old)
    tenant = 'synthetic-p12-ecs-' + uuid4().hex[:12]
    clients = {}
    for name, user, role in [('applicant', 'applicant-demo', 'applicant'),
                             ('safety-manager', 'safety-manager-demo', 'safety_manager')]:
        grant = {'token': secrets.token_urlsafe(48),
                 'identity': {'tenant_id': tenant, 'user_id': user},
                 'collaboration_role': role}
        config['tokens'].append(grant)
        clients[name] = {'schema_version': 'local-service-v1', 'tokens': [grant]}
        if role == 'safety_manager':
            config.setdefault('console_profiles', []).append(
                {'identity': grant['identity'], 'references': references})
    config.update(facts_dir=str(facts), console_work_package='P11-WP02')
    return config, clients


def merge_facts(legacy, fixture, tenant):
    result = copy.deepcopy(legacy)
    added = copy.deepcopy(fixture.get('records', []))
    for record in added:
        record['tenant_id'] = tenant
    result.setdefault('records', []).extend(added)
    return result


def validate_wheel(wheel, sha):
    require(digest(wheel.read_bytes()) == sha, 'Wheel fingerprint mismatch')
    with zipfile.ZipFile(wheel) as archive:
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and '..' not in path.parts
                    and '\\' not in item.filename and ':' not in item.filename
                    and (item.external_attr >> 16) & 0o170000 != 0o120000, 'Unsafe wheel entry')
        require('anlan/sql/017_collaboration.sql' in archive.namelist(), 'Missing SQL017')


def snapshot():
    import psycopg
    from psycopg import sql

    with psycopg.connect(environment()['ANLAN_DATABASE_URL']) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        names = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables "
                 "WHERE table_schema='anlan_v2' AND table_type='BASE TABLE' ORDER BY table_name")]
        rows = {}
        for name in names:
            if name.endswith('migrations'):
                continue
            documents = conn.execute(sql.SQL('SELECT to_jsonb(t) FROM anlan_v2.{} t').format(
                sql.Identifier(name))).fetchall()
            rows[name] = sorted(digest(json.dumps(r[0], sort_keys=True, default=str).encode())
                                for r in documents)
        packages = dict(conn.execute('SELECT work_package,count(*) FROM '
            'anlan_v2.model_budget_attempts WHERE authorization_id=%s GROUP BY 1', (AUTH,)))
        limits = conn.execute('SELECT total_limit,package_limit FROM '
            'anlan_v2.model_budget_authorizations WHERE authorization_id=%s', (AUTH,)).fetchone()
        conversation_limit = conn.execute('SELECT package_limit FROM '
            'anlan_v2.model_budget_package_limits WHERE authorization_id=%s AND '
            "work_package='P11-WP01'", (AUTH,)).fetchone()[0]
        pending = {key: conn.execute(query).fetchone()[0] for key, query in (
            ('pending_operations', 'SELECT count(*) FROM anlan_v2.anlan_operations '
             'WHERE result IS NULL'),
            ('pending_messages', 'SELECT count(*) FROM anlan_v2.conversation_messages '
             "WHERE status='pending'"),
            ('pending_reviews', 'SELECT count(*) FROM anlan_v2.perception_reviews '
             'WHERE result IS NULL'),
            ('reserved_attempts', 'SELECT count(*) FROM anlan_v2.model_budget_attempts '
             "WHERE status='reserved'"))}
        statuses = dict(conn.execute('SELECT status,count(*) FROM anlan_v2.model_budget_attempts '
                                    'WHERE authorization_id=%s GROUP BY 1', (AUTH,)))
        ledger = {'total': sum(packages.values()), 'conversation': packages.get('P11-WP01', 0),
                  'materials_events': packages.get('P11-WP02', 0), 'total_limit': limits[0],
                  'materials_events_limit': limits[1], 'conversation_limit': conversation_limit}
    return {'rows': rows, 'counts': {k: len(v) for k, v in rows.items()},
            'ledger': ledger, 'packages': packages, 'statuses': statuses, 'pending': pending}


def preserved(before, after):
    return all(not (Counter(values) - Counter(after['rows'].get(name, [])))
               for name, values in before['rows'].items())


def activation_gate(manifest, before, after):
    require(manifest.get('status') == 'prepared' and manifest.get('database_dump_sha256'),
            'Verified backup required')
    require(before['rows'] == after['rows'], 'Data changed since preparation; inspect first')


def private_json(path, document):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
    if hasattr(os, 'chown'):
        import pwd
        user = pwd.getpwnam('anlan2')
        os.chown(path, user.pw_uid, user.pw_gid)


def switch_release(target):
    require(target in (NEW, MAINTENANCE), 'Only P12 or maintenance may become active')
    pending = ROOT / ('current.p12-' + uuid4().hex)
    try:
        pending.symlink_to(target, target_is_directory=True)
        os.replace(pending, ROOT / 'current')
    finally:
        pending.unlink(missing_ok=True)


def request(path, token=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        with opener.open(urllib.request.Request('http://127.0.0.1:8018' + path,
                                               headers=headers), timeout=3) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def wait_maintenance():
    for _ in range(45):
        try:
            status, body = request('/tasks/rollback-probe/resume')
            if status == 503 and body.get('mode') == 'maintenance':
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('Maintenance 503 verification failed')


def wait_ready(config):
    for _ in range(60):
        try:
            infos = [request('/console/api/info', g['token']) for g in config['tokens']]
            if all(status == 200 and body.get('model_mode') == 'deepseek_live'
                   for status, body in infos):
                require(request('/console/api/info')[0] == 401, 'Anonymous access not denied')
                for grant, (_, body) in zip(config['tokens'], infos, strict=True):
                    require(body.get('collaboration_role') == grant.get('collaboration_role'),
                            'Trusted role mismatch')
                return [body for _, body in infos]
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('P12 authentication/readiness failed')


def rollback():
    require(MAINTENANCE.is_dir(), 'Prepared maintenance application required')
    command('systemctl', 'stop', 'anlan2-console')
    switch_release(MAINTENANCE)
    command('systemctl', 'start', 'anlan2-console')
    wait_maintenance()
    return {'status': 'maintenance', 'release': str(MAINTENANCE),
            'database_preserved': True, 'business_writes': False}


def prepare(wheel, sha, fixtures):
    require(os.geteuid() == 0, 'Scoped root deployment required')
    require((ROOT / 'current').resolve() == OLD, 'Unexpected current release')
    require(not any(p.exists() for p in (NEW, MAINTENANCE, BACKUP, PRIVATE)),
            'Already prepared; inspect rather than overwrite')
    validate_wheel(wheel, sha)
    before = snapshot()
    require_quiescent(before['pending'])
    plan = live_plan(before['ledger'])
    env = environment()
    BACKUP.mkdir(mode=0o700)
    for name in ('app.env', 'console.json'):
        shutil.copy2(SHARED / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    from psycopg.conninfo import conninfo_to_dict
    db = conninfo_to_dict(env['ANLAN_DATABASE_URL'])
    dump_env = env | {key: db[field] for key, field in (
        ('PGHOST', 'host'), ('PGPORT', 'port'), ('PGUSER', 'user'),
        ('PGPASSWORD', 'password'), ('PGDATABASE', 'dbname')) if field in db}
    dump_bin = next((str(p) for p in (Path('/usr/pgsql-13/bin/pg_dump'),
                                     Path('/usr/bin/pg_dump')) if p.is_file()), None)
    require(dump_bin is not None, 'Backup utility missing')
    dump = BACKUP / 'database.dump'
    command(dump_bin, '--format=custom', '--no-owner', '--no-acl', '--file=' + str(dump),
            env=dump_env)
    dump.chmod(0o600)
    command(str(Path(dump_bin).with_name('pg_restore')), '--list', str(dump))
    require(snapshot()['rows'] == before['rows'], 'Data changed during backup')
    private_json(BACKUP / 'data-before.json', before)
    private_json(BACKUP / 'recovery.json', {'old_release': str(OLD),
                 'forward_release': str(NEW), 'rollback': str(MAINTENANCE),
                 'policy': 'Never restore database or run legacy write API after SQL017'})
    for target in (NEW, MAINTENANCE):
        target.mkdir(mode=0o755)
        (target / 'venv').symlink_to((OLD / 'venv').resolve(), target_is_directory=True)
        (target / 'examples').symlink_to((OLD / 'examples').resolve(), target_is_directory=True)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(NEW / 'app')
    shutil.copy2(wheel, NEW / wheel.name)
    maintenance_pkg = MAINTENANCE / 'app/anlan/interfaces'
    maintenance_pkg.mkdir(parents=True)
    for path in (maintenance_pkg / '__init__.py', maintenance_pkg.parent / '__init__.py'):
        path.write_text('')
    (maintenance_pkg / 'serve.py').write_text(MAINTENANCE_SOURCE)
    PRIVATE.mkdir(mode=0o700)
    import pwd
    user = pwd.getpwnam('anlan2')
    os.chown(PRIVATE, user.pw_uid, user.pw_gid)
    facts = PRIVATE / 'facts'
    facts.mkdir(mode=0o700)
    os.chown(facts, user.pw_uid, user.pw_gid)
    old_config = json.loads((SHARED / 'console.json').read_text())
    config, clients = dual_config(old_config,
        json.loads((fixtures / 'perception-v1/refs.json').read_text()), facts)
    tenant = clients['applicant']['tokens'][0]['identity']['tenant_id']
    old_facts = Path(old_config['facts_dir'])
    fixture_facts = fixtures / 'perception-v1/facts'
    names = ({p.name for p in old_facts.glob('*.json')}
             | {p.name for p in fixture_facts.glob('*.json')})
    for name in names:
        legacy = (json.loads((old_facts / name).read_text())
                  if (old_facts / name).exists() else {'records': []})
        synthetic = (json.loads((fixture_facts / name).read_text())
                     if (fixture_facts / name).exists() else {'records': []})
        private_json(facts / name, merge_facts(legacy, synthetic, tenant))
    private_json(PRIVATE / 'service.json', config)
    for name, client in clients.items():
        private_json(PRIVATE / (name + '.json'), client)
    # Validate the new code/config/dependencies before changing the serving symlink.
    probe_env = env | {'PYTHONPATH': str(NEW / 'app')}
    command(str(NEW / 'venv/bin/python'), '-c',
        'from anlan.interfaces.service_config import ServiceConfig;'
        'from anlan.interfaces.api import create_app;'
        'ServiceConfig.from_file(' + repr(str(PRIVATE / 'service.json')) + ')', env=probe_env)
    prepared = snapshot()
    activation_gate({'status': 'prepared', 'database_dump_sha256': digest(dump.read_bytes())},
                    before, prepared)
    manifest = {'status': 'prepared', 'old_release': str(OLD), 'new_release': str(NEW),
                'maintenance_release': str(MAINTENANCE), 'wheel_sha256': sha,
                'database_dump_sha256': digest(dump.read_bytes()),
                'config_sha256': digest((SHARED / 'console.json').read_bytes()),
                'env_sha256': digest((SHARED / 'app.env').read_bytes()),
                'before_counts': before['counts'], 'ledger_before': before['ledger'],
                'live_plan': plan, 'new_tenant': tenant, 'new_model_requests': 0}
    private_json(NEW / 'rollout.json', manifest)
    return manifest


def activate():
    manifest_path = NEW / 'rollout.json'
    manifest = json.loads(manifest_path.read_text())
    require((ROOT / 'current').resolve() == OLD, 'Unexpected current release')
    require(digest((SHARED / 'console.json').read_bytes()) == manifest['config_sha256']
            and digest((SHARED / 'app.env').read_bytes()) == manifest['env_sha256'],
            'Private configuration changed')
    before = json.loads((BACKUP / 'data-before.json').read_text())
    activation_gate(manifest, before, snapshot())
    require(digest((BACKUP / 'database.dump').read_bytes()) == manifest['database_dump_sha256'],
            'Backup fingerprint changed')
    config_path = SHARED / 'console.json'
    config = json.loads((PRIVATE / 'service.json').read_text())
    command('systemctl', 'stop', 'anlan2-console')
    try:
        activation_gate(manifest, before, snapshot())
        # Same filesystem atomic replacement; owner and mode survive the switch.
        temporary = SHARED / ('console.p12-' + uuid4().hex)
        private_json(temporary, config)
        os.replace(temporary, config_path)
        switch_release(NEW)
        command('systemctl', 'start', 'anlan2-console')
        wait_ready(config)
        after = snapshot()
        require(preserved(before, after), 'Old rows changed')
        require(before['ledger'] == after['ledger'], 'Unexpected model requests')
    except Exception:
        rollback()
        raise RuntimeError('Activation failed; maintenance rollback active') from None
    manifest.update(status='activated', old_rows_preserved=True, after_counts=after['counts'],
                    ledger_after=after['ledger'])
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def forward():
    require((ROOT / 'current').resolve() == MAINTENANCE, 'Maintenance mode required')
    config = json.loads((SHARED / 'console.json').read_text())
    command('systemctl', 'stop', 'anlan2-console')
    switch_release(NEW)
    command('systemctl', 'start', 'anlan2-console')
    try:
        wait_ready(config)
    except Exception:
        rollback()
        raise RuntimeError('Forward recovery failed; maintenance remains active') from None
    return {'status': 'forward_recovered', 'database_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'prepare', 'activate', 'rollback', 'forward'])
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--fixtures', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'inspect':
            result = snapshot()
            result.pop('rows')
        elif args.action == 'prepare':
            result = prepare(args.wheel, args.sha256, args.fixtures)
        else:
            result = {'activate': activate, 'rollback': rollback, 'forward': forward}[args.action]()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'details': 'Private output hidden; inspect safe evidence'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
