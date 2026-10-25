"""User-authorized audit-only policy release; no paid probes or history reset."""
import importlib.util
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

spec = importlib.util.spec_from_file_location('p12_release',
    '/opt/anlan2/release-collaboration-20261025.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
BASE = r.ROOT / 'releases/p12-demo-tokens-20261025'
NEW = r.ROOT / 'releases/p12-audit-only-20261025'
BACKUP = r.SHARED / 'before-p12-audit-only-20261025'
CONFIG = r.SHARED / 'console.json'
SHA = '398635367cf5aed1a91153023a324f1b8b296c77124dbc2483abf832a5a0d572'
r.NEW = NEW  # Maintenance stays non-writable; forward targets the compatible build.


def preflight():
    r.require((r.ROOT / 'current').resolve() == BASE, 'Unexpected active release')
    r.require(not BACKUP.exists() and not NEW.exists(), 'Already prepared; inspect first')
    before = r.snapshot()
    r.require_quiescent(before['pending'])
    r.wait_ready(json.loads(CONFIG.read_text()))
    BACKUP.mkdir(mode=0o700)
    for name in ('app.env', 'console.json'):
        shutil.copy2(r.SHARED / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    r.private_json(BACKUP / 'before.json', before)
    r.private_json(BACKUP / 'recovery.json', {'base':str(BASE), 'forward':str(NEW),
        'maintenance':str(r.MAINTENANCE), 'policy':'Never restore DB or delete call records'})
    env = r.environment()
    db = conninfo_to_dict(env['ANLAN_DATABASE_URL'])
    dump_env = env | {key:db[field] for key, field in (
        ('PGHOST','host'), ('PGPORT','port'), ('PGUSER','user'),
        ('PGPASSWORD','password'), ('PGDATABASE','dbname')) if field in db}
    dump_bin = next(p for p in (Path('/usr/pgsql-13/bin/pg_dump'), Path('/usr/bin/pg_dump'))
                    if p.is_file())
    dump = BACKUP / 'database.dump'
    r.command(str(dump_bin), '--format=custom', '--no-owner', '--no-acl',
              '--file=' + str(dump), env=dump_env)
    dump.chmod(0o600)
    r.command(str(dump_bin.with_name('pg_restore')), '--list', str(dump))
    r.require(before['rows'] == r.snapshot()['rows'], 'Data changed during backup')
    return {'status':'preflight_ok', 'current':str(BASE), 'backup':str(BACKUP),
            'database_dump_sha256':r.digest(dump.read_bytes()), 'ledger':before['ledger'],
            'new_model_requests':0}


def prepare():
    r.require((r.ROOT / 'current').resolve() == BASE, 'Unexpected active release')
    r.require(not NEW.exists(), 'New release already exists; inspect first')
    wheel = BACKUP / 'anlan-0.1.0-py3-none-any.whl'
    r.validate_wheel(wheel, SHA)
    with zipfile.ZipFile(wheel) as archive:
        r.require('anlan/sql/018_model_call_policy.sql' in archive.namelist(), 'Missing SQL018')
        NEW.mkdir(mode=0o755)
        archive.extractall(NEW / 'app')
    shutil.copy2(wheel, NEW / wheel.name)
    for name in ('venv', 'examples'):
        (NEW / name).symlink_to((BASE / name).resolve(), target_is_directory=True)
    probe = r.environment() | {'PYTHONPATH':str(NEW / 'app')}
    r.command(str(NEW / 'venv/bin/python'), '-c',
        'from anlan.interfaces.service_config import ServiceConfig;'
        'ServiceConfig.from_file(' + repr(str(CONFIG)) + ')', env=probe)
    return {'status':'prepared', 'new_release':str(NEW), 'wheel_sha256':SHA,
            'new_model_requests':0}


def activate():
    r.require((r.ROOT / 'current').resolve() == BASE, 'Unexpected active release')
    config = json.loads(CONFIG.read_text())
    r.require_quiescent(r.snapshot()['pending'])
    try:
        r.command('systemctl', 'stop', 'anlan2-console')
        before = r.snapshot()
        r.require_quiescent(before['pending'])
        r.validate_wheel(NEW / 'anlan-0.1.0-py3-none-any.whl', SHA)
        with psycopg.connect(r.environment()['ANLAN_DATABASE_URL']) as conn:
            conn.execute((NEW / 'app/anlan/sql/018_model_call_policy.sql').read_text(),
                         prepare=False)
            row = conn.execute('SELECT authorization_id FROM '
                'anlan_v2.model_budget_authorizations WHERE authorization_id=%s FOR UPDATE',
                (r.AUTH,)).fetchone()
            r.require(row is not None, 'Current authorization missing')
            conn.execute('INSERT INTO anlan_v2.model_call_policies '
                '(authorization_id,limits_enforced,reason) VALUES (%s,false,%s)',
                (r.AUTH, 'User explicitly requested no project call quotas on 2026-10-25'))
        r.switch_release(NEW)
        r.command('systemctl', 'start', 'anlan2-console')
        infos = r.wait_ready(config)
        for info in infos:
            r.require(info['budget']['status'] == 'audit_only'
                      and info['budget']['limits_enforced'] is False
                      and info['budget']['total_limit'] is None
                      and info['budget']['package_limit'] is None
                      and info['budget']['package_remaining'] is None
                      and info['conversation_budget']['package_limit'] is None,
                      'Audit-only information mismatch')
        after = r.snapshot()
        r.require(r.preserved(before, after), 'Old business/audit rows changed')
        r.require(before['ledger'] == after['ledger'], 'Unexpected model requests')
        root_sha = r.digest(urllib.request.urlopen('http://127.0.0.1/').read())
        r.require(root_sha == 'b5a7f25ac949b5f26ded8692c39c42f64f85cb919736f5db68bc776987515b12',
                  'Original website changed')
    except Exception:
        r.rollback()
        raise RuntimeError('Activation failed; maintenance active; DB history retained') from None
    report = {'status':'activated', 'current':str(NEW), 'backup':str(BACKUP),
        'wheel_sha256':SHA, 'limits_enforced':False, 'old_rows_preserved':True,
        'attempt_history_unchanged':True, 'attempts':after['ledger']['total'],
        'package_usage':{'P11-WP01':after['ledger']['conversation'],
                         'P11-WP02':after['ledger']['materials_events']},
        'effective_total_limit':None, 'effective_package_limit':None,
        'new_model_requests':0, 'root_site_unchanged':True,
        'roles':[{'role':info.get('collaboration_role'), 'budget':info['budget'],
                  'conversation_budget':info['conversation_budget']} for info in infos]}
    r.private_json(BACKUP / 'activated.json', report)
    return report


if __name__ == '__main__':
    try:
        action = sys.argv[1]
        result = {'preflight':preflight, 'prepare':prepare, 'activate':activate,
                  'rollback':r.rollback, 'forward':r.forward}[action]()
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'status':'failed', 'error_type':type(exc).__name__,
                          'details':'Private output hidden'}))
        raise SystemExit(1)
