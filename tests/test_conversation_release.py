import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "deploy/aliyun/release_conversation.py"
spec = importlib.util.spec_from_file_location("conversation_release", MODULE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_rollback_initializer_keeps_latest_constraint_without_changing_reservations():
    source = '''class Ledger:
    async def initialize(self):
        async with self.connect() as conn:
            await conn.execute(files("anlan").joinpath("sql/010_console_live_budget.sql"))
            migration = files("anlan").joinpath("sql/011_console_materials_v2_budget.sql")
            await conn.execute(migration.read_text(), prepare=False)
            await conn.execute(
                "INSERT INTO authorizations VALUES (1)")
    def reserve(self):
        return "old reservation path"
'''
    patched = release.patch_legacy_initializer(source)
    assert "sql/015_conversation_release_budget.sql" in patched
    assert "sql/010_" not in patched and "sql/011_" not in patched
    assert 'return "old reservation path"' in patched
    assert '"INSERT INTO authorizations VALUES (1)"' in patched


def test_unrecognized_rollback_source_is_rejected_before_writing():
    with pytest.raises(RuntimeError, match="Unexpected old budget"):
        release.patch_legacy_initializer("class Unrecognized: pass")


def test_historical_fingerprints_may_only_be_added_to_not_removed_or_changed():
    before = {"rows": {name: ["old"] for name in release.TABLES}}
    after = {"rows": {name: ["old", "new"] for name in release.TABLES}}
    assert release.preserved(before, after)
    after["rows"]["model_budget_attempts"] = ["changed"]
    assert not release.preserved(before, after)
