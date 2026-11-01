"""P13 ECS deployment helpers preserve history and add only synthetic P13 fixtures."""

import importlib.util
import sys
import zipfile
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def deployment():
    spec = importlib.util.spec_from_file_location(
        "release_preflight", ROOT / "deploy/aliyun/release_preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config():
    return {
        "schema_version": "local-service-v1",
        "model_mode": "deepseek_live",
        "as_of": "2026-09-22T04:00:00+00:00",
        "tokens": [
            {
                "token": "legacy-token",
                "identity": {"tenant_id": "tenant-a", "user_id": "owner"},
            },
            {
                "token": "applicant-token",
                "identity": {"tenant_id": "tenant-a", "user_id": "applicant"},
                "collaboration_role": "applicant",
            },
            {
                "token": "manager-token",
                "identity": {"tenant_id": "tenant-a", "user_id": "manager"},
                "collaboration_role": "safety_manager",
            },
        ],
        "facts_dir": "/old/facts",
        "console_profiles": [
            {
                "identity": {"tenant_id": "tenant-a", "user_id": "manager"},
                "references": {
                    "worker_id": "worker-old",
                    "qualification_type": "welding",
                    "area_id": "area-old",
                },
            }
        ],
    }


def access():
    return {
        "data_origin": "SYNTHETIC",
        "version": "old",
        "records": [
            {
                "tenant_id": "tenant-a",
                "user_id": "applicant",
                "worker_ids": ["worker-old"],
                "area_ids": ["area-old"],
            },
            {
                "tenant_id": "tenant-a",
                "user_id": "manager",
                "worker_ids": ["worker-old"],
                "area_ids": ["area-old"],
            },
        ],
    }


def test_p13_config_preserves_tokens_and_adds_catalog(tmp_path):
    result = deployment().dual_config(config(), tmp_path / "facts", access())
    assert result["tokens"] == config()["tokens"]
    assert result["facts_dir"] == str(tmp_path / "facts")
    assert result["console_profiles"] == config()["console_profiles"]
    catalog = result["precheck_catalogs"]
    assert len(catalog) == 1
    assert catalog[0]["tenant_id"] == "tenant-a"
    assert {item["worker_id"] for item in catalog[0]["workers"]} == {
        "worker-p13-normal",
        "worker-p13-alert",
    }
    assert {item["area_id"] for item in catalog[0]["areas"]} == {
        "area-p13-normal",
        "area-p13-restricted",
    }


def test_p13_fact_merge_adds_acl_and_business_records():
    module = deployment()
    merged = module.merge_facts(
        access(),
        {
            "qualifications.json": {
                "data_origin": "SYNTHETIC",
                "version": "px",
                "records": [
                    {
                        "tenant_id": "tenant-a",
                        "record_id": "q-normal",
                        "object_id": "worker-p13-normal",
                    }
                ],
            }
        },
        ("applicant", "manager"),
        "tenant-a",
    )
    for record in merged["access.json"]["records"]:
        assert "worker-p13-normal" in record["worker_ids"]
        assert "area-p13-restricted" in record["area_ids"]
    assert merged["qualifications.json"]["records"][-1]["record_id"] == "q-normal"


def test_p13_wheel_requires_runtime_resources(tmp_path):
    module = deployment()
    wheel = tmp_path / "release.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("anlan/__init__.py", "")
    with pytest.raises(ValueError, match="preflight"):
        module.validate_wheel(wheel)


def test_p13_activation_paths_are_fixed():
    module = deployment()
    assert module.OLD.name == "p12-audit-only-20261025"
    assert module.NEW.name == "p13-preflight-20261101"
    assert module.MAINTENANCE.name == "p12-maintenance-20261025"
    with pytest.raises(ValueError, match="fixed"):
        module.require_fixed_path(Path("/tmp/untrusted"))


def test_precheck_read_probe_targets_the_assigned_manager(monkeypatch):
    module = deployment()
    statements = []

    class Connection(AbstractContextManager):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement, params):
            statements.append((statement, params))
            return self

        def fetchone(self):
            return ("task-assigned",)

    fake_psycopg = type(
        "Psycopg",
        (),
        {"connect": staticmethod(lambda dsn: Connection())},
    )
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    class Remote:
        def environment(self):
            return {"ANLAN_DATABASE_URL": "host=localhost"}

        def request(self, path, token):
            assert token == "manager-token"
            return 200, {
                "required": True,
                "legacy_completed": False,
                "status": "not_checked",
            }

    result = module._precheck_read_probe(Remote(), config())
    assert result == {"task_id": "task-assigned", "status": "not_checked"}
    assert "reviewer_user_id=%s" in statements[0][0]
    assert statements[0][1] == ("tenant-a", "manager")
