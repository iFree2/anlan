"""Scoped P11 release with a database backup and budget-compatible old-UI rollback."""
import argparse
import ast
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from uuid import uuid4

ROOT = Path('/opt/anlan2')
OLD = ROOT / 'releases/p8-materials-v2-budget-20261008'
NEW = ROOT / 'releases/p11-conversation-20261022'
FALLBACK = ROOT / 'releases/p11-previous-ui-20261022'
SHARED = ROOT / 'shared'
BACKUP = SHARED / 'before-p11-conversation-20261022'
TABLES = ('anlan_tasks', 'anlan_operations', 'perception_events',
          'perception_reviews', 'model_budget_attempts')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def environment():
    env = os.environ.copy()
    for line in (SHARED / 'app.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, separator, value = line.partition('=')
            if separator:
                env[key] = shlex.split(value)[0] if value else ''
    return env


def command(*args, env=None, timeout=120):
    result = subprocess.run(args, capture_output=True, env=env, timeout=timeout)
    require(result.returncode == 0, 'Management command failed; output hidden')
    return result.stdout.decode().strip()


def data_snapshot():
    import psycopg
    rows = {}
    with psycopg.connect(environment()['ANLAN_DATABASE_URL']) as conn:
        for table in TABLES:
            documents = conn.execute('SELECT to_jsonb(t) FROM anlan_v2.' + table + ' t').fetchall()
            rows[table] = sorted(digest(json.dumps(row[0], sort_keys=True, default=str).encode())
                                 for row in documents)
        packages = dict(conn.execute(
            'SELECT work_package,count(*) FROM anlan_v2.model_budget_attempts '
            'WHERE authorization_id=%s GROUP BY work_package',
            ('20260920-long-term-v1',)).fetchall())
    return {'rows': rows, 'counts': {name: len(values) for name, values in rows.items()},
            'packages': packages}


def preserved(before, after):
    return all(not (Counter(before['rows'][name]) - Counter(after['rows'][name]))
               for name in TABLES)


def patch_legacy_initializer(source):
    begin = source.find('            await conn.execute(files("anlan").joinpath("sql/010_')
    end = source.find('            await conn.execute(\n                "INSERT INTO', begin)
    require(begin >= 0 and end > begin, 'Unexpected old budget initialization; inspect first')
    source = source[:begin] + (
        '            migration = files("anlan").joinpath('
        '"sql/015_conversation_release_budget.sql")\n'
        '            await conn.execute(migration.read_text(encoding="utf-8"), prepare=False)\n'
    ) + source[end:]
    ast.parse(source)
    return source


def replace_file(path, content, stat):
    fd, name = tempfile.mkstemp(prefix=path.name + '.p11-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.st_mode & 0o777)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def switch_release(target):
    pending = ROOT / ('current.p11-' + uuid4().hex)
    try:
        pending.symlink_to(target, target_is_directory=True)
        os.replace(pending, ROOT / 'current')
    finally:
        pending.unlink(missing_ok=True)


def wait_ready(config):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(45):
        try:
            req = urllib.request.Request('http://127.0.0.1:8018/console/api/info',
                headers={'Authorization': 'Bearer ' + config['tokens'][0]['token']})
            with opener.open(req, timeout=2) as response:
                info = json.load(response)
            if info.get('model_mode') == 'deepseek_live' and info.get('budget', {}).get(
                    'status') == 'available':
                return info
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('Application readiness timeout')


def prepare(wheel, expected_digest):
    require(os.geteuid() == 0, 'Scoped root deployment required')
    require((ROOT / 'current').resolve() == OLD, 'Unexpected active release')
    require(not any(path.exists() for path in (NEW, FALLBACK, BACKUP)),
            'Release already prepared; inspect existing state')
    require(digest(wheel.read_bytes()) == expected_digest, 'Wheel fingerprint mismatch')
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
    dump_binary = next((str(path) for path in (
        Path('/usr/pgsql-13/bin/pg_dump'), Path('/usr/bin/pg_dump')) if path.is_file()), None)
    require(dump_binary is not None, 'PostgreSQL backup utility unavailable')
    dump = BACKUP / 'database.dump'
    command(dump_binary, '--format=custom', '--no-owner', '--no-acl',
            '--file=' + str(dump), env=dump_env)
    dump.chmod(0o600)
    before = data_snapshot()
    (BACKUP / 'data-before.json').write_text(json.dumps(before))
    for release in (NEW, FALLBACK):
        release.mkdir(mode=0o755)
        (release / 'venv').symlink_to((OLD / 'venv').resolve(), target_is_directory=True)
        (release / 'examples').symlink_to((OLD / 'examples').resolve(), target_is_directory=True)
        if (OLD / 'model-budget.json').exists():
            (release / 'model-budget.json').symlink_to((OLD / 'model-budget.json').resolve())
    with zipfile.ZipFile(wheel) as archive:
        require(all(not Path(name).is_absolute() and '..' not in Path(name).parts
                    for name in archive.namelist()), 'Unsafe wheel entry')
        for name in ('anlan/sql/013_conversations.sql',
                     'anlan/sql/015_conversation_release_budget.sql'):
            require(name in archive.namelist(), 'Missing release migration')
        (NEW / 'app').mkdir(mode=0o755)
        archive.extractall(NEW / 'app')
    shutil.copy2(wheel, NEW / wheel.name)
    shutil.copytree(OLD / 'app', FALLBACK / 'app')
    legacy = FALLBACK / 'app/anlan/infrastructure/budget.py'
    legacy.write_text(patch_legacy_initializer(legacy.read_text()))
    shutil.copy2(NEW / 'app/anlan/sql/015_conversation_release_budget.sql',
                 FALLBACK / 'app/anlan/sql/015_conversation_release_budget.sql')
    for release in (NEW, FALLBACK):
        probe_env = env | {'PYTHONPATH': str(release / 'app')}
        command(str(release / 'venv/bin/python'), '-c',
                'import anlan;from anlan.interfaces.api import create_app;'
                'assert ' + repr(str(release / 'app')) + ' in anlan.__file__', env=probe_env)
    config = json.loads((SHARED / 'console.json').read_text())
    require(config.get('model_mode') == 'deepseek_live', 'Expected live configuration')
    manifest = {'status': 'prepared', 'old_release': str(OLD), 'new_release': str(NEW),
                'fallback_release': str(FALLBACK), 'wheel_sha256': expected_digest,
                'database_dump_sha256': digest(dump.read_bytes()),
                'env_sha256': digest((SHARED / 'app.env').read_bytes()),
                'config_sha256': digest((SHARED / 'console.json').read_bytes()),
                'before_counts': before['counts'], 'before_packages': before['packages']}
    (NEW / 'rollout.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def rollback():
    config_path = SHARED / 'console.json'
    config = json.loads((BACKUP / 'console.json').read_text())
    command('systemctl', 'stop', 'anlan2-console')
    replace_file(config_path, (BACKUP / 'console.json').read_bytes(), config_path.stat())
    switch_release(FALLBACK)
    command('systemctl', 'start', 'anlan2-console')
    wait_ready(config)
    return {'status': 'rolled_back', 'release': str(FALLBACK), 'database_preserved': True}


def activate():
    manifest = json.loads((NEW / 'rollout.json').read_text())
    require(manifest['status'] == 'prepared', 'Prepared release required')
    require((ROOT / 'current').resolve() == OLD, 'Active release changed')
    require(digest((SHARED / 'app.env').read_bytes()) == manifest['env_sha256'],
            'Private environment changed')
    config_path = SHARED / 'console.json'
    require(digest(config_path.read_bytes()) == manifest['config_sha256'],
            'Service configuration changed')
    before = json.loads((BACKUP / 'data-before.json').read_text())
    config = json.loads(config_path.read_text())
    config['console_work_package'] = 'P11-WP02'
    try:
        command('systemctl', 'stop', 'anlan2-console')
        replace_file(config_path, json.dumps(config).encode(), config_path.stat())
        switch_release(NEW)
        command('systemctl', 'start', 'anlan2-console')
        info = wait_ready(config)
        after = data_snapshot()
        require(preserved(before, after), 'Historical row fingerprints changed')
        require(before['counts'] == after['counts'], 'Unexpected business writes during activation')
    except Exception:
        rollback()
        raise RuntimeError('Activation failed; compatible old-UI rollback verified') from None
    manifest.update(status='activated', old_rows_preserved=True,
                    after_counts=after['counts'], material_budget=info['budget'],
                    model_mode=info['model_mode'], new_model_requests=0)
    (NEW / 'rollout.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'activate', 'rollback'])
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    try:
        result = prepare(args.wheel, args.sha256) if args.action == 'prepare' else (
            activate() if args.action == 'activate' else rollback())
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'details': 'Operation failed; private configuration hidden'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
