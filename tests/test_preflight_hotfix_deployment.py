"""P13 legacy-change hotfix uses a new immutable release path."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def deployment():
    spec = importlib.util.spec_from_file_location(
        "release_preflight_hotfix",
        ROOT / "deploy/aliyun/release_preflight_hotfix.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hotfix_paths_never_overwrite_first_p13_release():
    module = deployment()
    assert module.BASE.name == "p13-preflight-20261101"
    assert module.NEW.name == "p13-preflight-20261101b"
    assert module.NEW != module.BASE
    assert module.BACKUP.name == "before-p13-hotfix-20261101"
