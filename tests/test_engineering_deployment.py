"""Offline release gates: no SSH, database or provider calls."""

import copy
import importlib.util
import json
import types
import zipfile
from pathlib import Path

import pytest


def release():
    path = Path("deploy/aliyun/release_engineering.py")
    assert path.is_file(), "engineering release implementation missing"
    spec = importlib.util.spec_from_file_location("engineering_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_preserves_query_baseline_and_pins_current_artifact():
    m = release()
    assert m.BASE.name == "business-query-20261117"
    assert m.NEW.name == "engineering-20261119"
    assert m.BACKUP.name == "before-engineering-20261119"
    assert m.WHEEL_SHA == "9b8f72e5d26b58d3f40af1d797b8d455952fce728d2c655218a3d93c44b2d901"
    assert "anlan/sql/021_business_queries.sql" in m.REQUIRED
    assert "anlan/tools/dynamic_mcp/execution.py" in m.REQUIRED


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a\\..\\escape"])
def test_unsafe_archive_is_rejected(tmp_path, name):
    m = release()
    path = tmp_path / "bad.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        m.validate_wheel(path, m.digest(path.read_bytes()))


def test_missing_query_and_engineering_resources_are_rejected(tmp_path):
    m = release()
    path = tmp_path / "missing.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("anlan/__init__.py", "")
    with pytest.raises(ValueError, match="Missing"):
        m.validate_wheel(path, m.digest(path.read_bytes()))


@pytest.mark.parametrize("change", ["append", "delete", "ledger", "packages", "statuses"])
def test_no_business_or_query_audit_mutation_is_permitted(change):
    m = release()
    before = dict(
        rows={"business_query_receipts": ["old"]},
        ledger={"total": 146},
        packages={"p": 1},
        statuses={"completed": 1},
    )
    after = copy.deepcopy(before)
    if change == "append":
        after["rows"]["business_query_receipts"].append("new")
    elif change == "delete":
        after["rows"]["business_query_receipts"].clear()
    else:
        after[change]["extra"] = 1
    with pytest.raises(ValueError):
        m.assert_preserved(before, after)


def configured(monkeypatch, tmp_path, fail=None):
    m = release()
    root = tmp_path / "root"
    paths = {name: root / name.lower() for name in ["BASE", "NEW", "BACKUP", "MAINTENANCE"]}
    for path in paths.values():
        path.mkdir(parents=True)
    active = [paths["BASE"]]
    resolve = Path.resolve

    def resolve_current(path, *args, **kwargs):
        return active[0] if path == root / "current" else resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_current)
    for name, value in paths.items():
        monkeypatch.setattr(m, name, value)
    monkeypatch.setattr(m, "ROOT", root)
    monkeypatch.setattr(m, "SHARED", root)
    for name in ["CONFIG", "ENV"]:
        path = root / ("console.json" if name == "CONFIG" else "app.env")
        path.write_text("{}" if name == "CONFIG" else "PRIVATE-SENTINEL")
        monkeypatch.setattr(m, name, path)
        (paths["BACKUP"] / ("console.json" if name == "CONFIG" else "app.env")).write_bytes(
            path.read_bytes()
        )
    dump = m.BACKUP / "database.dump"
    dump.write_bytes(b"backup")
    wheel = m.NEW / m.WHEEL_NAME
    wheel.write_bytes(b"wheel")
    before = dict(
        rows={"anlan_tasks": ["old"], "business_query_receipts": ["q"]},
        counts={"anlan_tasks": 1},
        ledger={"total": 146},
        packages={"p": 1},
        statuses={"completed": 1},
        pending={"precheck_jobs": 0, "precheck_attempts": 0},
    )
    (m.BACKUP / "before.json").write_text(json.dumps(before))
    (m.BACKUP / "systemd.json").write_text("{}")
    manifest = dict(
        status="prepared",
        wheel_sha256=m.digest(wheel.read_bytes()),
        database_dump_sha256=m.digest(dump.read_bytes()),
        config_sha256=m.digest(m.CONFIG.read_bytes()),
        env_sha256=m.digest(m.ENV.read_bytes()),
        systemd_sha256=m.digest(b"{}"),
        migrations_before=[1, 17, 18, 19, 20, 21],
        source_commit="a" * 40,
        dependencies=m.EXPECTED_DEPENDENCIES,
    )
    (m.NEW / "rollout.json").write_text(json.dumps(manifest))
    calls = []
    snapshots = [copy.deepcopy(before) for _ in range(4)]
    if fail in {"data", "ledger"}:
        if fail == "data":
            snapshots[2]["rows"]["anlan_tasks"].clear()
        else:
            snapshots[2]["ledger"]["total"] = 147

    def command(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("systemctl", fail):
            raise RuntimeError("PRIVATE-FAILURE")
        return "999"

    def switch(path):
        calls.append(("switch", path))
        active[0] = path

    def rollback():
        calls.append(("rollback",))
        if fail == "rollback":
            raise RuntimeError("PRIVATE-ROLLBACK")
        active[0] = m.MAINTENANCE

    def verify(h):
        if fail in {"verify", "rollback"}:
            raise RuntimeError("PRIVATE-VERIFY")
        return dict(migrations=manifest["migrations_before"], zero_write_probe=True)

    h = types.SimpleNamespace(
        command=command,
        switch_release=switch,
        rollback=rollback,
        wait_maintenance=lambda: calls.append(("maintenance_503",)),
        private_json=lambda path, document: path.write_text(json.dumps(document)),
    )
    monkeypatch.setattr(m, "harness", lambda: h)
    monkeypatch.setattr(m.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(m, "snapshot", lambda _: snapshots.pop(0))
    monkeypatch.setattr(m, "systemd_metadata", lambda _: (m.digest(b"{}"), {}))
    monkeypatch.setattr(m, "migration_versions", lambda _: manifest["migrations_before"])
    monkeypatch.setattr(m, "validate_wheel", lambda *args: manifest["wheel_sha256"])
    monkeypatch.setattr(m, "verify_dependencies", lambda *args: None)
    monkeypatch.setattr(m, "verify_active", verify)
    monkeypatch.setattr(m, "write_report", lambda path, doc: path.write_text(json.dumps(doc)))
    return m, calls, snapshots


def test_activation_has_no_migration_and_preserves_every_row(monkeypatch, tmp_path):
    m, calls, _ = configured(monkeypatch, tmp_path)
    result = m.activate()
    assert result["status"] == "activated" and result["new_model_requests"] == 0
    assert calls.index(("systemctl", "stop", "anlan2-console")) < calls.index(("switch", m.NEW))
    assert not any("migration" in str(c) or "pg_restore" in str(c) for c in calls)


@pytest.mark.parametrize("fail", ["stop", "start", "verify", "data", "ledger"])
def test_post_stop_failure_proves_maintenance_without_restore(monkeypatch, tmp_path, fail):
    m, calls, _ = configured(monkeypatch, tmp_path, fail)
    with pytest.raises(RuntimeError, match="maintenance_verified") as caught:
        m.activate()
    assert "PRIVATE" not in str(caught.value)
    assert ("rollback",) in calls and ("maintenance_503",) in calls
    assert (m.ROOT / "current").resolve() == m.MAINTENANCE


def test_failed_rollback_does_not_claim_maintenance(monkeypatch, tmp_path):
    m, calls, _ = configured(monkeypatch, tmp_path, "rollback")
    with pytest.raises(RuntimeError, match="recovery_failed"):
        m.activate()
    assert ("maintenance_503",) not in calls


@pytest.mark.parametrize("gate", ["config", "migration", "precheck"])
def test_pre_stop_guard_refuses_changes_without_stopping(monkeypatch, tmp_path, gate):
    m, calls, snapshots = configured(monkeypatch, tmp_path)
    if gate == "config":
        m.CONFIG.write_text("changed")
    elif gate == "migration":
        monkeypatch.setattr(m, "migration_versions", lambda _: [21, 22])
    else:
        snapshots[0]["pending"]["precheck_jobs"] = 1
    with pytest.raises(ValueError):
        m.activate()
    assert calls == []


def test_changed_state_after_stop_enters_maintenance(monkeypatch, tmp_path):
    m, calls, snapshots = configured(monkeypatch, tmp_path)
    snapshots[1]["pending"]["precheck_attempts"] = 1
    with pytest.raises(RuntimeError, match="maintenance_verified"):
        m.activate()
    assert ("rollback",) in calls


def test_forward_requires_maintenance_state(monkeypatch, tmp_path):
    m, calls, _ = configured(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        m.activate(forward=True)
    assert calls == []


def test_helper_fingerprint_checked_before_import(monkeypatch, tmp_path):
    m = release()
    path = tmp_path / "helper.py"
    path.write_text("raise RuntimeError('must not execute')")
    with pytest.raises(ValueError, match="helper fingerprint"):
        m.load_helper(path, "0" * 64, "not_loaded")


def test_remote_query_helper_pin_matches_verified_wire_bytes():
    m = release()
    assert m.HELPERS["release-business-query-20261117.py"] == (
        "c7a78de56d70339b08ced0a9c8a2f204bbc252a36206b3d0cc6b6cc7fa2d32ae"
    )


def preparation(monkeypatch, tmp_path, fail=None):
    m, calls, states = configured(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "NEW", m.NEW / "candidate")
    monkeypatch.setattr(m, "BACKUP", m.BACKUP / "candidate")
    wheel = tmp_path / "input.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("anlan/__init__.py", "")
    monkeypatch.setattr(m, "CONFIG_SHA", m.digest(m.CONFIG.read_bytes()))
    q = types.SimpleNamespace(dependency_signature=lambda _: ("deps", "python"))
    monkeypatch.setattr(m, "query_helper", lambda: q)
    h = m.harness()
    m.test_links = []

    def link(path, target, target_is_directory=False):
        assert path.parent == m.NEW and target == (m.BASE / path.name).resolve()
        assert target_is_directory
        m.test_links.append((path, target))
        path.mkdir()

    monkeypatch.setattr(Path, "symlink_to", link)
    h.private_json = lambda p, d: p.write_text(json.dumps(d))
    h.wait_ready = lambda _: None

    def backup(_, directory):
        if fail == "backup":
            raise RuntimeError("PRIVATE-BACKUP")
        path = directory / "database.dump"
        path.write_bytes(b"backup")
        if fail == "config_during_backup":
            m.CONFIG.write_text("changed-during-backup")
        elif fail == "env_during_backup":
            m.ENV.write_text("changed-during-backup")
        return m.digest(path.read_bytes())

    monkeypatch.setattr(
        m, "load_helper", lambda *args: types.SimpleNamespace(_backup_database=backup)
    )
    if fail == "pending_before":
        states[0]["pending"]["precheck_jobs"] = 1
    elif fail == "pending_after":
        states[1]["pending"]["precheck_attempts"] = 1
    elif fail == "migration":
        monkeypatch.setattr(m, "migration_versions", lambda _: [21, 22])
    elif fail == "dependency":

        def dependency(*args):
            raise ValueError("Dependency mismatch")

        monkeypatch.setattr(m, "verify_dependencies", dependency)

    def probe(*args):
        if fail == "import":
            raise ValueError("Import mismatch")
        if fail == "systemd_during_probe":
            monkeypatch.setattr(m, "systemd_metadata", lambda _: ("changed", {}))
        return {"modules": 154}

    monkeypatch.setattr(m, "import_probe", probe)
    return m, calls, wheel


def test_prepare_backs_up_and_does_not_touch_service(monkeypatch, tmp_path):
    m, calls, wheel = preparation(monkeypatch, tmp_path)
    report = m.prepare(wheel, "a" * 40)
    assert report["status"] == "prepared" and report["migrations_before"] == [1, 17, 18, 19, 20, 21]
    assert len(m.test_links) == 2 and (m.NEW / "rollout.json").is_file()
    assert calls == []


@pytest.mark.parametrize(
    "failure",
    [
        "backup",
        "config_during_backup",
        "env_during_backup",
        "systemd_during_probe",
        "pending_before",
        "pending_after",
        "migration",
        "dependency",
        "import",
    ],
)
def test_prepare_failures_never_stop_service(monkeypatch, tmp_path, failure):
    m, calls, wheel = preparation(monkeypatch, tmp_path, failure)
    with pytest.raises((ValueError, RuntimeError)):
        m.prepare(wheel, "a" * 40)
    assert calls == []


def test_changed_backup_configuration_aborts_before_stop(monkeypatch, tmp_path):
    m, calls, _ = configured(monkeypatch, tmp_path)
    (m.BACKUP / "console.json").write_text("changed")
    with pytest.raises(ValueError):
        m.activate()
    assert calls == []


@pytest.mark.parametrize("kind", ["config", "env", "systemd"])
def test_stop_time_fingerprint_change_prevents_new_service_start(monkeypatch, tmp_path, kind):
    m, calls, _ = configured(monkeypatch, tmp_path)
    h = m.harness()
    command = h.command

    def changing(*args, **kwargs):
        result = command(*args, **kwargs)
        if args[:2] == ("systemctl", "stop"):
            if kind == "config":
                m.CONFIG.write_text("changed")
            elif kind == "env":
                m.ENV.write_text("changed")
            else:
                monkeypatch.setattr(m, "systemd_metadata", lambda _: ("changed", {}))
        return result

    h.command = changing
    with pytest.raises(RuntimeError, match="maintenance_verified"):
        m.activate()
    assert ("switch", m.NEW) not in calls


def test_import_probe_constructs_real_crlf_bytes_without_network_or_database():
    import ast

    m = release()
    observed = []

    def command(*args, **kwargs):
        tree = ast.parse(args[2])
        raw = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, bytes)
        ]
        assert raw == [b"SYNTHETIC engineering probe\r\n"]
        assert b"\\r\\n" not in raw[0]
        observed.append(True)
        return '{"modules":154,"txt_draft_unpublished":true}'

    h = types.SimpleNamespace(command=command, environment=lambda: {})
    assert m.import_probe(h, Path("/candidate"))["txt_draft_unpublished"]
    assert observed == [True]


@pytest.mark.parametrize("change", ["append", "update"])
def test_forward_preserves_legitimate_post_release_state(monkeypatch, tmp_path, change):
    m, calls, states = configured(monkeypatch, tmp_path)
    current = copy.deepcopy(states[0])
    if change == "append":
        current["rows"]["anlan_tasks"].append("legitimate-new-task")
    else:
        current["rows"]["anlan_tasks"] = ["legitimate-updated-task"]
    monkeypatch.setattr(m, "snapshot", lambda _: copy.deepcopy(current))
    original = (m.BACKUP / "before.json").read_bytes()
    m.rollback()
    result = m.activate(forward=True)
    assert result["status"] == "activated"
    assert (m.BACKUP / "before.json").read_bytes() == original
    assert current["rows"]["anlan_tasks"] != ["old"]


def test_forward_refuses_drift_after_maintenance_snapshot(monkeypatch, tmp_path):
    m, calls, states = configured(monkeypatch, tmp_path)
    current = copy.deepcopy(states[0])
    monkeypatch.setattr(m, "snapshot", lambda _: copy.deepcopy(current))
    m.rollback()
    calls.clear()
    current["rows"]["anlan_tasks"].append("drift")
    with pytest.raises(ValueError):
        m.activate(forward=True)
    assert calls == []
