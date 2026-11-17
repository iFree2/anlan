"""Release gates and failure injection never restore old writes or erase audit data."""

import copy
import importlib.util
import json
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def deployment():
    spec = importlib.util.spec_from_file_location(
        "release_business_query", ROOT / "deploy/aliyun/release_business_query.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_release_and_pinned_artifact_are_independent_of_current_release():
    m = deployment()
    assert m.BASE.name == "p13-preflight-20261101b"
    assert m.NEW.name == "business-query-20261117" and m.NEW != m.BASE
    assert m.MAINTENANCE.name == "p12-maintenance-20261025"
    assert m.WHEEL_SHA == "fd2c20866774f2c03a3e3ce6a5e3cd9ea79fc29c3c04b03c5ad1ef67c9b975e0"


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a\\..\\escape"])
def test_wheel_validation_rejects_traversal_before_extract(tmp_path, name):
    m = deployment()
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(name, "unsafe")
    with pytest.raises(ValueError, match="Unsafe"):
        m.validate_wheel(wheel, m.digest(wheel.read_bytes()))


def test_artifact_requires_query_contracts_and_sql021(tmp_path):
    m = deployment()
    wheel = tmp_path / "missing.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("anlan/__init__.py", "")
    with pytest.raises(ValueError, match="query resources"):
        m.validate_wheel(wheel, m.digest(wheel.read_bytes()))


def setup_activation(monkeypatch, tmp_path, *, fail=None):
    m = deployment()
    root = tmp_path / "root"
    base, new, maintenance, backup = [
        root / name for name in ("base", "new", "maintenance", "backup")
    ]
    for path in (base, new, maintenance, backup):
        path.mkdir(parents=True)
    active = [base]
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == root / "current":
            return active[0]
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    config = root / "console.json"
    config.write_text('{"model_mode":"deepseek_live","tokens":[]}', encoding="utf-8")
    env = root / "app.env"
    env.write_text("PRIVATE-SENTINEL", encoding="utf-8")
    (backup / "database.dump").write_bytes(b"database-backup")
    wheel = new / "anlan-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"verified-wheel")
    before = {
        "rows": {"model_budget_attempts": ["old-attempt"], "anlan_tasks": ["old-task"]},
        "ledger": {"total": 142},
        "counts": {"model_budget_attempts": 142},
        "pending": {"pending_operations": 0},
    }
    (backup / "before.json").write_text(json.dumps(before))
    manifest = {
        "status": "prepared",
        "wheel_sha256": m.digest(wheel.read_bytes()),
        "database_dump_sha256": m.digest((backup / "database.dump").read_bytes()),
        "config_sha256": m.digest(config.read_bytes()),
        "env_sha256": m.digest(env.read_bytes()),
        "systemd_sha256": "unit-hash",
    }
    (new / "rollout.json").write_text(json.dumps(manifest))
    for name, value in (
        ("ROOT", root),
        ("BASE", base),
        ("NEW", new),
        ("BACKUP", backup),
        ("MAINTENANCE", maintenance),
        ("CONFIG", config),
        ("ENV", env),
    ):
        monkeypatch.setattr(m, name, value)
    observed = []
    snapshots = [copy.deepcopy(before), copy.deepcopy(before), copy.deepcopy(before)]
    if fail == "old_row_loss":
        snapshots[-1]["rows"]["anlan_tasks"] = []
    if fail == "model_call":
        snapshots[-1]["ledger"]["total"] = 143

    def command(*args, **kwargs):
        observed.append(args)
        if args[:2] == ("systemctl", fail):
            raise RuntimeError("PRIVATE-FAILURE")
        return "active" if "is-active" in args else "4321"

    def switch(target):
        observed.append(("switch", target))
        active[0] = target

    def rollback():
        observed.append(("maintenance", maintenance))
        switch(maintenance)

    def migrate(h):
        observed.append(("migration", 21))
        if fail == "migration":
            raise RuntimeError("PRIVATE-MIGRATION")

    def verify(h):
        observed.append(("verify",))
        if fail == "verify":
            raise RuntimeError("PRIVATE-VERIFY")
        return {"roles": ["legacy", "applicant", "safety_manager"], "migrations": [21]}

    h = types.SimpleNamespace(
        command=command,
        snapshot=lambda: snapshots.pop(0),
        require_quiescent=lambda pending: m.require(not any(pending.values()), "Pending work"),
        rollback=rollback,
        switch_release=switch,
    )
    monkeypatch.setattr(m, "harness", lambda: h)
    monkeypatch.setattr(m.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(m, "systemd_metadata", lambda h: ("unit-hash", {}))
    monkeypatch.setattr(m, "validate_wheel", lambda *args: manifest["wheel_sha256"])
    monkeypatch.setattr(m, "migrate", migrate)
    monkeypatch.setattr(m, "verify_active", verify)
    monkeypatch.setattr(m, "write_report", lambda path, doc: path.write_text(json.dumps(doc)))
    return m, observed, before


@pytest.mark.parametrize(
    "failure", ["stop", "migration", "start", "verify", "old_row_loss", "model_call"]
)
def test_activation_failure_enters_maintenance_without_restoring_database(
    monkeypatch, tmp_path, failure
):
    m, observed, _ = setup_activation(monkeypatch, tmp_path, fail=failure)
    with pytest.raises(RuntimeError, match="maintenance") as error:
        m.activate()
    assert "PRIVATE" not in str(error.value)
    assert (m.ROOT / "current").resolve() == m.MAINTENANCE
    assert ("maintenance", m.MAINTENANCE) in observed
    assert not any("pg_restore" in str(item) or "DELETE" in str(item) for item in observed)


def test_activation_orders_stop_migrate_switch_start_and_preserves_private_config(
    monkeypatch, tmp_path
):
    m, observed, _ = setup_activation(monkeypatch, tmp_path)
    old_config, old_env = m.CONFIG.read_bytes(), m.ENV.read_bytes()
    result = m.activate()
    assert result["status"] == "activated" and result["new_model_requests"] == 0
    assert m.CONFIG.read_bytes() == old_config and m.ENV.read_bytes() == old_env
    assert observed.index(("systemctl", "stop", "anlan2-console")) < observed.index(
        ("migration", 21)
    )
    assert observed.index(("migration", 21)) < observed.index(("switch", m.NEW))
    assert observed.index(("switch", m.NEW)) < observed.index(
        ("systemctl", "start", "anlan2-console")
    )


def test_changed_configuration_aborts_before_service_stop(monkeypatch, tmp_path):
    m, observed, _ = setup_activation(monkeypatch, tmp_path)
    m.CONFIG.write_text("changed")
    with pytest.raises(ValueError, match="Configuration"):
        m.activate()
    assert observed == []
