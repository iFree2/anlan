"""Deploy the P13 legacy-changes_requested compatibility fix to a new release."""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path("/opt/anlan2")
BASE = ROOT / "releases/p13-preflight-20261101"
NEW = ROOT / "releases/p13-preflight-20261101b"
MAINTENANCE = ROOT / "releases/p12-maintenance-20261025"
SHARED = ROOT / "shared"
CONFIG = SHARED / "p13-preflight-20261101/service.json"
BACKUP = SHARED / "before-p13-hotfix-20261101"
WHEEL_SHA = "dcbee436820eebf43c4dbd3231f3c3941d4d352704a58b9338727b6c8d970680"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def modules():
    for name, path in (
        ("release_p13", ROOT / "release-preflight-20261101.py"),
        ("release_p12", ROOT / "release-collaboration-20261025.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module


def harnesses():
    return tuple(modules())


def prepare(wheel=None, expected_sha=WHEEL_SHA):
    p13, p12 = harnesses()
    wheel = Path(wheel or BACKUP / "anlan-0.1.0-py3-none-any.whl")
    require(os.geteuid() == 0, "Scoped root deployment required")
    require((ROOT / "current").resolve() == BASE, "Unexpected active release")
    require(not NEW.exists() and not BACKUP.exists(), "Hotfix already prepared")
    p13.validate_wheel(wheel, expected_sha)
    before = p12.snapshot()
    p12.require_quiescent(before["pending"])
    p12.wait_ready(json.loads(CONFIG.read_text()))
    BACKUP.mkdir(mode=0o700)
    for name in ("app.env",):
        shutil.copy2(SHARED / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    p12.private_json(BACKUP / "service.json", json.loads(CONFIG.read_text()))
    p12.private_json(BACKUP / "before.json", before)
    p12.private_json(
        BACKUP / "recovery.json",
        {
            "base": str(BASE),
            "forward": str(NEW),
            "maintenance": str(MAINTENANCE),
            "policy": "Never restore the database or the legacy write release.",
        },
    )
    NEW.mkdir(mode=0o755)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(NEW / "app")
    shutil.copy2(wheel, NEW / wheel.name)
    for name in ("venv", "examples"):
        (NEW / name).symlink_to((BASE / name).resolve(), target_is_directory=True)
    probe_env = p12.environment() | {"PYTHONPATH": str(NEW / "app")}
    p12.command(
        str(NEW / "venv/bin/python"),
        "-c",
        "from anlan.interfaces.service_config import ServiceConfig;"
        "ServiceConfig.from_file(" + repr(str(CONFIG)) + ")",
        env=probe_env,
    )
    report = {
        "status": "prepared",
        "base": str(BASE),
        "new_release": str(NEW),
        "wheel_sha256": expected_sha,
        "config_sha256": digest(CONFIG.read_bytes()),
        "before_counts": before["counts"],
        "ledger_before": before["ledger"],
        "new_model_requests": 0,
    }
    p12.private_json(NEW / "hotfix.json", report)
    return report


def activate():
    p13, p12 = harnesses()
    require(os.geteuid() == 0, "Scoped root deployment required")
    require((ROOT / "current").resolve() == BASE, "Unexpected active release")
    manifest = json.loads((NEW / "hotfix.json").read_text())
    require(digest(CONFIG.read_bytes()) == manifest["config_sha256"],
            "P13 configuration changed")
    p12.validate_wheel(
        NEW / "anlan-0.1.0-py3-none-any.whl",
        manifest["wheel_sha256"],
    )
    before = p12.snapshot()
    p12.require_quiescent(before["pending"])
    config = json.loads(CONFIG.read_text())
    try:
        p12.command("systemctl", "stop", "anlan2-console")
        p12.NEW = NEW
        p12.switch_release(NEW)
        p12.command("systemctl", "start", "anlan2-console")
        infos, probe, migrations = p13._verify_active(p12, config)
        after = p12.snapshot()
        require(p12.preserved(before, after), "Existing rows changed")
        require(before["ledger"] == after["ledger"], "Unexpected model request")
    except Exception:
        p12.rollback()
        raise RuntimeError("Hotfix activation failed; maintenance remains active") from None
    report = {
        **manifest,
        "status": "activated",
        "current": str(NEW),
        "service_pid": p12.command(
            "systemctl", "show", "-p", "MainPID", "--value", "anlan2-console"
        ),
        "roles": [
            {"role": item.get("collaboration_role"), "model_mode": info.get("model_mode")}
            for item, info in zip(config["tokens"], infos, strict=True)
        ],
        "anonymous_status": 401,
        "p13_console_asset": True,
        "precheck_read_probe": probe,
        "migrations": migrations,
        "old_rows_preserved": True,
        "ledger_unchanged": True,
        "new_model_requests": 0,
    }
    (NEW / "hotfix.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def rollback():
    _, p12 = harnesses()
    return p12.rollback()


def forward():
    p13, p12 = harnesses()
    require((ROOT / "current").resolve() == MAINTENANCE, "Maintenance mode required")
    config = json.loads(CONFIG.read_text())
    p12.command("systemctl", "stop", "anlan2-console")
    p12.NEW = NEW
    p12.switch_release(NEW)
    p12.command("systemctl", "start", "anlan2-console")
    try:
        infos, probe, migrations = p13._verify_active(p12, config)
    except Exception:
        p12.rollback()
        raise RuntimeError("Forward recovery failed; maintenance remains active") from None
    return {
        "status": "activated",
        "current": str(NEW),
        "roles": [
            {"role": item.get("collaboration_role"), "model_mode": info.get("model_mode")}
            for item, info in zip(config["tokens"], infos, strict=True)
        ],
        "anonymous_status": 401,
        "p13_console_asset": True,
        "precheck_read_probe": probe,
        "migrations": migrations,
        "new_model_requests": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate", "rollback", "forward"])
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sha256", default=WHEEL_SHA)
    args = parser.parse_args()
    try:
        result = (
            prepare(args.wheel, args.sha256)
            if args.action == "prepare"
            else {"activate": activate, "rollback": rollback, "forward": forward}[args.action]()
        )
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "details": "Private output hidden",
        }))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
