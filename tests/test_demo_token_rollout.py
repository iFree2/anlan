"""Run the actual Linux activation function with deterministic management faults."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def activation():
    source = Path('deploy/aliyun/release_demo_tokens.py').read_text('utf-8')
    tree = ast.parse(source)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'activate')
    module = ast.Module(body=[function], type_ignores=[])
    return compile(module, 'release_demo_tokens.py', 'exec')


def test_first_snapshot_failure_after_stop_restores_original_app_and_config(tmp_path):
    backup, base = tmp_path / 'backup', tmp_path / 'current'
    backup.mkdir()
    base.mkdir()
    grants = [{'token': 'a' * 64, 'collaboration_role': 'applicant'},
              {'token': 'b' * 64, 'collaboration_role': 'safety_manager'}]
    document = {'schema_version': 'local-service-v1', 'tokens': grants}
    paths = []
    for index in range(4):
        path = tmp_path / ('config-' + str(index) + '.json')
        path.write_text(json.dumps(document))
        (backup / (str(index) + '.json')).write_text(json.dumps(document))
        paths.append(path)
    (backup / 'new-service.json').write_text(json.dumps(document))
    observed, calls = [], []

    def snapshot():
        calls.append('snapshot')
        if len(calls) == 2:
            raise RuntimeError('injected first post-stop snapshot fault')
        return {'pending': {}}

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    release = SimpleNamespace(ROOT=tmp_path, require=require, snapshot=snapshot,
        require_quiescent=lambda pending: None,
        command=lambda *args: observed.append(args),
        wait_ready=lambda config: observed.append('original-ready'))
    namespace = {'r': release, 'BASE': base, 'BACKUP': backup, 'PATHS': paths,
                 'json': json, 'write_config': lambda path, doc: observed.append(path),
                 'switch': lambda target: observed.append(target)}
    exec(activation(), namespace)
    with pytest.raises(RuntimeError, match='original P12 configs/application restored'):
        namespace['activate']()
    assert ('systemctl', 'start', 'anlan2-console') in observed
    assert observed[-1] == 'original-ready'
    assert base in observed and all(path in observed for path in paths)
