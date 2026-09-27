import importlib.util

import pytest


def test_ci_rejects_changed_source_but_ignores_generated_bytecode(tmp_path):
    spec = importlib.util.spec_from_file_location("ci_checks", "scripts/ci.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "src/anlan/sample.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    before = module.source_fingerprints(tmp_path)
    cache = source.parent / "__pycache__"
    cache.mkdir()
    (cache / "sample.pyc").write_bytes(b"generated")
    assert module.verify_sources(before, tmp_path) == before
    source.write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        module.verify_sources(before, tmp_path)
