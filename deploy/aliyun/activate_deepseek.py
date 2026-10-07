"""Explicit one-time rollout on the inspected host; key arrives only on stdin.

Reuses the previous release's immutable dependency environment. Never bootstraps
databases, imports budgets, or resets counters. A failed activation restores the
previous application/configuration while retaining the additive SQL migration.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

ROOT = Path("/opt/anlan2")
OLD = ROOT / "releases/p8-console-20261007"
NEW = ROOT / "releases/p8-deepseek-20261007"
SHARED = ROOT / "shared"
BACKUP = SHARED / "before-p8-deepseek-20261007"


class RolloutFailure(RuntimeError):
    def __init__(self, verified, errors):
        super().__init__("Activation failed; inspect rollback status")
        self.rollback_verified, self.rollback_errors = verified, errors


def require(value, message):
    if not value:
        raise RuntimeError(message)


def command(*args):
    result = subprocess.run(args, capture_output=True, timeout=90)
    require(result.returncode == 0, "Management command failed; output hidden")
    return result.stdout.decode().strip()


def replace_file(path, data, uid, gid):
    fd, name = tempfile.mkstemp(prefix=path.name + ".p8-live-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def switch_release(target):
    pending = ROOT / ("current.p8-live-" + uuid4().hex)
    try:
        pending.symlink_to(target, target_is_directory=True)
        os.replace(pending, ROOT / "current")
    finally:
        pending.unlink(missing_ok=True)


def wait_ready(config, mode):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        try:
            request = urllib.request.Request("http://127.0.0.1:8018/console/api/info",
                headers={"Authorization": "Bearer " + config["tokens"][0]["token"]})
            with opener.open(request, timeout=2) as response:
                info = json.load(response)
            if (info.get("model_mode") == mode
                    and (mode != "deepseek_live" or (
                        info.get("material_mode") == mode
                        and info.get("budget", {}).get("status") == "available"))):
                return info
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Application did not become ready")


def prepare(wheel, digest):
    require(os.geteuid() == 0, "Root required for this scoped rollout")
    require((ROOT / "current").resolve() == OLD, "Unexpected current release")
    require(not NEW.exists() and not BACKUP.exists(), "Rollout already prepared; inspect first")
    require(hashlib.sha256(wheel.read_bytes()).hexdigest() == digest, "Wheel digest differs")
    with zipfile.ZipFile(wheel) as archive:
        require(all(not Path(n).is_absolute() and ".." not in Path(n).parts
                    for n in archive.namelist()), "Unsafe archive path")
        require("anlan/sql/010_console_live_budget.sql" in archive.namelist(), "Missing migration")
        NEW.mkdir(mode=0o755)
        (NEW / "app").mkdir(mode=0o755)
        archive.extractall(NEW / "app")
    shutil.copy2(wheel, NEW / wheel.name)
    (NEW / "venv").symlink_to(OLD / "venv", target_is_directory=True)
    (NEW / "examples").symlink_to(OLD / "examples", target_is_directory=True)
    (NEW / "model-budget.json").symlink_to(OLD / "model-budget.json")
    probe = subprocess.run(
        [str(NEW / "venv/bin/python"), "-c",
         "from anlan.interfaces.service_models import ServiceModels;"
         "import anlan;assert '/p8-deepseek-20261007/app/' in anlan.__file__"],
        env={**os.environ, "PYTHONPATH": str(NEW / "app")},
        capture_output=True, timeout=40,
    )
    require(probe.returncode == 0, "New release import failed; output hidden")
    BACKUP.mkdir(mode=0o700)
    for name in ("app.env", "console.json"):
        shutil.copy2(SHARED / name, BACKUP / name)
        (BACKUP / name).chmod(0o600)
    report = {"status": "prepared", "previous_release": str(OLD), "release": str(NEW),
              "wheel_sha256": digest, "dependencies_reused": True,
              "cloud_mode_changed": False, "credentials_recorded": False}
    (NEW / "rollout.json").write_text(json.dumps(report))
    return report


def activate():
    require(os.geteuid() == 0 and NEW.is_dir() and BACKUP.is_dir(), "Prepared rollout required")
    require((ROOT / "current").resolve() == OLD, "Unexpected current release")
    key = json.load(sys.stdin)["api_key"]
    require(isinstance(key, str) and re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", key),
            "Invalid provider key shape; value hidden")
    env_path, config_path = SHARED / "app.env", SHARED / "console.json"
    for path in (env_path, config_path):
        require(path.read_bytes() == (BACKUP / path.name).read_bytes(),
                "Configuration changed after preparation")
    env_stat, config_stat = env_path.stat(), config_path.stat()
    env = env_path.read_text()
    require(not any(line.startswith(("DEEPSEEK_API_KEY=", "PYTHONPATH="))
                    for line in env.splitlines()), "Unexpected existing model environment")
    config = json.loads(config_path.read_text())
    require(config.get("model_mode", "scripted_double") == "scripted_double",
            "Unexpected existing model mode")
    config["model_mode"] = "deepseek_live"
    next_env = env.rstrip() + "\nPYTHONPATH=/opt/anlan2/current/app\nDEEPSEEK_API_KEY=" + key + "\n"
    before_pid = command("systemctl", "show", "anlan2-console", "--property=MainPID", "--value")
    try:
        command("systemctl", "stop", "anlan2-console")
        replace_file(env_path, next_env.encode(), env_stat.st_uid, env_stat.st_gid)
        replace_file(config_path, json.dumps(config).encode(),
                     config_stat.st_uid, config_stat.st_gid)
        switch_release(NEW)
        command("systemctl", "start", "anlan2-console")
        info = wait_ready(config, "deepseek_live")
    except Exception:
        errors = []
        old_config = json.loads((BACKUP / "console.json").read_text())
        steps = [
            ("stop", lambda: command("systemctl", "stop", "anlan2-console")),
            ("release", lambda: switch_release(OLD)),
            ("environment", lambda: replace_file(env_path, (BACKUP / "app.env").read_bytes(),
                                                  env_stat.st_uid, env_stat.st_gid)),
            ("config", lambda: replace_file(config_path, (BACKUP / "console.json").read_bytes(),
                                             config_stat.st_uid, config_stat.st_gid)),
            ("restart", lambda: command("systemctl", "restart", "anlan2-console")),
        ]
        for name, operation in steps:
            try:
                operation()
            except Exception:
                errors.append(name)
        verified = False
        try:
            wait_ready(old_config, old_config.get("model_mode", "scripted_double"))
            verified = ((ROOT / "current").resolve() == OLD and all(
                (SHARED / name).read_bytes() == (BACKUP / name).read_bytes()
                for name in ("app.env", "console.json")))
        except Exception:
            errors.append("readiness")
        raise RolloutFailure(verified, errors) from None
    return {"status": "activated", "previous_release": str(OLD), "release": str(NEW),
            "before_pid": int(before_pid), "after_pid": int(command(
                "systemctl", "show", "anlan2-console", "--property=MainPID", "--value")),
            "model_mode": info["model_mode"], "material_mode": info["material_mode"],
            "model": info["model"], "budget": info["budget"],
            "new_model_requests": 0, "credentials_recorded": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate"])
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    try:
        result = prepare(args.wheel, args.sha256) if args.action == "prepare" else activate()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "rollback_verified": getattr(exc, "rollback_verified", None),
                          "rollback_errors": getattr(exc, "rollback_errors", []),
                          "details": "Deployment failed; credential/configuration text hidden"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
