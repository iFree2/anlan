"""P13 release Gate validates local-only configuration and packaged resources."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def verifier():
    spec = importlib.util.spec_from_file_location(
        "preflight_release", ROOT / "scripts/verify_preflight_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grants():
    return [
        {
            "token": role,
            "identity": {"tenant_id": "synthetic", "user_id": role},
            "collaboration_role": role,
        }
        for role in ("applicant", "safety_manager")
    ]


def valid_config():
    return {
        "model_mode": "scripted_double",
        "tokens": grants(),
        "as_of": "2026-09-22T04:00:00+00:00",
        "precheck_catalogs": [
            {
                "tenant_id": "synthetic",
                "workers": [
                    {
                        "worker_id": "worker-p13-normal",
                        "label": "SYNTHETIC normal worker",
                        "qualification_types": [
                            {"qualification_type": "welding", "label": "SYNTHETIC welding"}
                        ],
                    }
                ],
                "areas": [
                    {"area_id": "area-p13-normal", "label": "SYNTHETIC normal area"}
                ],
            }
        ],
    }


@pytest.mark.parametrize("mode", ["deepseek_live", None])
def test_preflight_release_requires_explicit_scripted_mode(mode):
    with pytest.raises(ValueError, match="scripted_double"):
        verifier().validate_config(valid_config() | {"model_mode": mode})


def test_preflight_release_rejects_same_identity_and_missing_catalog():
    same = grants()
    same[1]["identity"]["user_id"] = same[0]["identity"]["user_id"]
    with pytest.raises(ValueError, match="distinct"):
        verifier().validate_config(valid_config() | {"tokens": same})
    with pytest.raises(ValueError, match="catalog"):
        verifier().validate_config(valid_config() | {"precheck_catalogs": []})


def test_preflight_wheel_resources_include_routes_sql_and_console(tmp_path):
    module = verifier()
    resources = [
        *(ROOT / "src/anlan").rglob("*.py"),
        *(ROOT / "src/anlan/sql").glob("*.sql"),
        *(ROOT / "src/anlan/assets").glob("*"),
        *[p for p in (ROOT / "src/anlan/interfaces/console/assets").rglob("*") if p.is_file()],
    ]
    wheel = tmp_path / "anlan-p13-resources.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for resource in resources:
            archive.writestr(resource.relative_to(ROOT / "src").as_posix(), resource.read_bytes())
    with zipfile.ZipFile(wheel) as archive:
        checked = module.verify_resources(archive, ROOT)
    paths = {item["path"] for item in checked}
    assert "anlan/sql/019_preflight_bindings.sql" in paths
    assert "anlan/sql/020_preflight_checks.sql" in paths
    assert "anlan/interfaces/preflight_routes.py" in paths
    assert "anlan/interfaces/console/assets/app.js" in paths


def test_preflight_release_refuses_live_or_remote_configuration(monkeypatch):
    module = verifier()
    with pytest.raises(ValueError, match="loopback"):
        module.verify(Path("unused.whl"), Path("unused.json"), "host=203.0.113.10 dbname=demo")
    monkeypatch.setenv("PGPASSWORD", "PRIVATE-SENTINEL")
    with pytest.raises(ValueError, match="loopback") as error:
        module.verify(Path("unused.whl"), Path("unused.json"), "host=localhost dbname=demo")
    assert "PRIVATE-SENTINEL" not in str(error.value)


def test_preflight_release_output_is_new_only(tmp_path):
    module = verifier()
    output = tmp_path / "evidence.json"
    output.write_text(json.dumps({"old": True}), encoding="utf-8")
    with pytest.raises(FileExistsError):
        module.new_output(output)
