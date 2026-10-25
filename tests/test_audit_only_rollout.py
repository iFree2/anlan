"""Read actual deployment functions without importing remote-only dependencies."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


def activation():
    source = Path('deploy/aliyun/release_audit_only.py').read_text('utf-8')
    tree = ast.parse(source)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'activate')
    return compile(ast.Module(body=[function], type_ignores=[]), 'release_audit_only.py', 'exec')


def test_activation_failures_after_stop_enter_maintenance_without_database_restore(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{}')
    current = tmp_path / 'current'
    current.mkdir()
    observed, snapshots = [], []

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def snapshot():
        snapshots.append(True)
        if len(snapshots) > 1:
            raise RuntimeError('post-stop database unavailable')
        return {'pending': {}}

    release = SimpleNamespace(ROOT=tmp_path, SHARED=tmp_path,
        require=require, require_quiescent=lambda value: None, snapshot=snapshot,
        command=lambda *args: observed.append(args),
        rollback=lambda: observed.append('maintenance'))
    namespace = {'r':release, 'BASE':current,
                 'CONFIG':config, 'json':__import__('json')}
    exec(activation(), namespace)
    with pytest.raises(RuntimeError, match='maintenance'):
        namespace['activate']()
    assert ('systemctl', 'stop', 'anlan2-console') in observed
    assert observed[-1] == 'maintenance'
    assert not any('pg_restore' in str(item) for item in observed)
