"""Verify wheel imports/resources and preserved command interfaces outside the source directory."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    report = {"status": "running", "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "resources": [], "commands": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        try:
            with zipfile.ZipFile(wheel) as archive:
                for path in [*(ROOT / "src/anlan/sql").glob("*.sql"),
                             *(ROOT / "src/anlan/assets").glob("*")]:
                    name = path.relative_to(ROOT / "src").as_posix()
                    if archive.read(name) != path.read_bytes():
                        raise ValueError("Wheel resource differs from source")
                    report["resources"].append({"path": name, "sha256": hashlib.sha256(
                        archive.read(name)).hexdigest()})
                entries = archive.read("anlan-0.1.0.dist-info/entry_points.txt").decode()
                if "anlan = anlan.interfaces.cli:main" not in entries:
                    raise ValueError("Console entry not updated")
            with tempfile.TemporaryDirectory(prefix="anlan-wheel-check-") as temporary:
                code = """
import importlib,json,pkgutil,sys
from importlib.resources import files
sys.path.insert(0,sys.argv[1])
import anlan
modules=[]
for item in pkgutil.walk_packages(anlan.__path__, 'anlan.'):
    if item.name.endswith('.__main__'): continue
    module=importlib.import_module(item.name)
    if sys.argv[1] not in module.__file__: raise ValueError('Import escaped wheel')
    modules.append(item.name)
print(json.dumps({'modules':modules,'resource_bytes':len(files('anlan').joinpath('sql/001_registry.sql').read_bytes())}))
"""
                result = subprocess.run([sys.executable, "-I", "-c", code, str(wheel)],
                    cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=30)
                if result.returncode:
                    raise ValueError("Wheel isolated import failed")
                report["isolated_imports"] = json.loads(result.stdout)
                for module in ("anlan", "anlan.cli", "anlan.memory_cli", "anlan.review_cli",
                               "anlan.multi_review_cli", "anlan.interfaces.cli"):
                    command = ("import runpy,sys;sys.path.insert(0,sys.argv[1]);"
                               "module=sys.argv[2];sys.argv=[module,'--help'];"
                               "runpy.run_module(module,run_name='__main__')")
                    result = subprocess.run(
                        [sys.executable, "-I", "-c", command, str(wheel), module],
                        cwd=temporary, capture_output=True, timeout=15,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                    report["commands"].append({"module": module, "returncode": result.returncode})
                    if result.returncode != 0:
                        raise ValueError("Compatibility CLI failed")
            if len(report["resources"]) != 5:
                raise ValueError("Expected four migrations and one guidance resource")
            report["status"] = "completed"
        except Exception as exc:
            report.update(status="failed", error_category=type(exc).__name__)
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "resources": len(report["resources"]),
                      "commands": len(report["commands"])}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
