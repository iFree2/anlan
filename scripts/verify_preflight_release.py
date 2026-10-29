"""Local-only P13 wheel Gate: preflight block, rebind, restart, evidence and event.

The secure PostgreSQL target parsing, wheel provenance and process lifecycle are
shared with the reviewed P12 release harness. This Gate adds the P13 business
invariants and never calls a live model or remote service.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
_HARNESS_SPEC = importlib.util.spec_from_file_location(
    "collaboration_release_harness", ROOT / "scripts/verify_collaboration_release.py"
)
HARNESS = importlib.util.module_from_spec(_HARNESS_SPEC)
_HARNESS_SPEC.loader.exec_module(HARNESS)


def verify_resources(archive, root):
    resources = HARNESS.verify_resources(archive, root)
    for path in sorted((Path(root) / "src/anlan").rglob("*.py")):
        name = path.relative_to(Path(root) / "src").as_posix()
        content = archive.read(name)
        if content != path.read_bytes():
            raise ValueError("Wheel module differs from source")
        resources.append({
            "path": name,
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    return resources


def validate_config(config):
    if config.get("model_mode") != "scripted_double":
        raise ValueError("Gate requires explicit scripted_double mode")
    applicants = [
        grant for grant in config.get("tokens", [])
        if grant.get("collaboration_role") == "applicant"
    ]
    managers = [
        grant for grant in config.get("tokens", [])
        if grant.get("collaboration_role") == "safety_manager"
    ]
    for applicant in applicants:
        for manager in managers:
            left = applicant.get("identity", {})
            right = manager.get("identity", {})
            if (
                left.get("tenant_id") == right.get("tenant_id")
                and left.get("user_id")
                and right.get("user_id")
                and left["user_id"] != right["user_id"]
            ):
                _validate_catalog(config, left["tenant_id"])
                return applicant, manager
    raise ValueError("Gate needs distinct same-tenant participants")


def _validate_catalog(config, tenant_id):
    catalog = next(
        (item for item in config.get("precheck_catalogs", [])
         if item.get("tenant_id") == tenant_id),
        None,
    )
    if not catalog or not catalog.get("workers") or not catalog.get("areas"):
        raise ValueError("Gate needs a nonempty precheck catalog for the participant tenant")
    return catalog


def new_output(path):
    if path.exists():
        raise FileExistsError(path)
    return path


def _request(client, method, path, payload=None, status=200):
    response = client.request(method, path, json=payload)
    if response.status_code != status:
        raise AssertionError(
            f"P13 Gate HTTP {method} {path}: {response.status_code} {response.text[:300]}"
        )
    return response.json()


def _wait_for(client, path, statuses, *, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = _request(client, "GET", path)
        if value.get("status") in statuses:
            return value
        if value.get("execution_status") == "failed":
            raise AssertionError(f"P13 precheck execution failed: {value.get('issues')}")
        time.sleep(0.1)
    raise AssertionError(f"P13 precheck status deadline exceeded: {statuses}")


def _free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def verify(wheel, config_path, dsn):
    dsn = HARNESS.loopback_dsn(dsn)
    config_path = Path(config_path).resolve()
    wheel = Path(wheel).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    applicant, manager = validate_config(config)
    catalog = _validate_catalog(config, applicant["identity"]["tenant_id"])
    alert_worker = next(
        item for item in catalog["workers"] if item["worker_id"] == "worker-p13-alert"
    )
    normal_worker = next(
        item for item in catalog["workers"] if item["worker_id"] == "worker-p13-normal"
    )
    restricted_area = next(
        item for item in catalog["areas"] if item["area_id"] == "area-p13-restricted"
    )
    normal_area = next(
        item for item in catalog["areas"] if item["area_id"] == "area-p13-normal"
    )
    alert_type = alert_worker["qualification_types"][0]["qualification_type"]
    normal_type = normal_worker["qualification_types"][0]["qualification_type"]
    with wheel.open("rb") as stream:
        wheel_sha256 = hashlib.sha256(stream.read()).hexdigest()
    import zipfile

    with zipfile.ZipFile(wheel) as archive:
        resources = verify_resources(archive, ROOT)
    port = _free_port()
    directory = Path(tempfile.mkdtemp(prefix="anlan-b4-wheel-")).resolve()
    configured_cache = Path(config.get("embeddings_cache", ".runtime/embeddings"))
    if not configured_cache.is_absolute():
        config["embeddings_cache"] = str((ROOT / configured_cache).resolve())
    normalized_config = directory / "service.json"
    normalized_config.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    server = HARNESS.WheelServer(wheel, normalized_config, dsn, directory, port)
    report = {
        "status": "running",
        "phase": "P13",
        "model_mode": "scripted_double",
        "database_target": {
            "kind": "single_explicit_loopback",
            "address_pinned": True,
            "pg_environment": "nonempty_rejected_all_removed",
        },
        "wheel_sha256": wheel_sha256,
        "resources": resources,
        "credentials_recorded": False,
        "real_model_requests": 0,
    }
    try:
        report["cwd_outside_source"] = not directory.is_relative_to(ROOT)
        server.start()
        base = f"http://127.0.0.1:{port}"
        with (
            httpx.Client(
                base_url=base,
                trust_env=False,
                timeout=30,
                headers={"Authorization": "Bearer " + applicant["token"]},
            ) as a,
            httpx.Client(
                base_url=base,
                trust_env=False,
                timeout=30,
                headers={"Authorization": "Bearer " + manager["token"]},
            ) as b,
        ):
            fields = {
                "work_location_description": "SYNTHETIC台架",
                "work_object_description": "SYNTHETIC试件",
                "work_method_description": "焊接演示",
                "attachment_description": "SYNTHETIC示意图",
            }
            task = _request(
                a,
                "POST",
                "/tasks",
                {"request_id": uuid4().hex, "fields": fields},
            )["task_id"]
            shared_path = f"/collaboration/applications/{task}"
            precheck_path = shared_path + "/prechecks"
            binding_path = shared_path + "/binding"
            alert_binding = _request(
                a,
                "POST",
                binding_path,
                {
                    "request_id": uuid4().hex,
                    "expected_material_revision": 1,
                    "expected_binding_revision": 0,
                    "worker_id": alert_worker["worker_id"],
                    "qualification_type": alert_type,
                    "area_id": restricted_area["area_id"],
                },
            )
            assert alert_binding["binding_revision"] == 1
            _request(
                a,
                "POST",
                shared_path + "/commands/submit",
                {
                    "request_id": uuid4().hex,
                    "expected_application_version": 1,
                    "expected_material_revision": 1,
                    "expected_binding_revision": 1,
                    "reviewer_user_id": manager["identity"]["user_id"],
                },
            )
            blocked = _wait_for(b, precheck_path, {"gap", "failed"})
            assert blocked["status"] == "gap"
            assert blocked["binding"]["references"]["worker_id"] == "worker-p13-alert"
            assert blocked["binding"]["references"]["area_id"] == "area-p13-restricted"
            assert "worker_not_current_active" in blocked["issues"]
            assert "area_not_current_normal" in blocked["issues"]

            _request(
                b,
                "POST",
                shared_path + "/commands/request_changes",
                {
                    "request_id": uuid4().hex,
                    "expected_application_version": 2,
                    "expected_material_revision": 1,
                    "questions": ["SYNTHETIC: use current worker and normal area"],
                },
            )
            normal_binding = _request(
                a,
                "POST",
                binding_path,
                {
                    "request_id": uuid4().hex,
                    "expected_material_revision": 1,
                    "expected_binding_revision": 1,
                    "worker_id": normal_worker["worker_id"],
                    "qualification_type": normal_type,
                    "area_id": normal_area["area_id"],
                },
            )
            assert normal_binding["binding_revision"] == 2

            resubmit = {
                "request_id": uuid4().hex,
                "expected_application_version": 3,
                "expected_material_revision": 1,
                "expected_binding_revision": 2,
                "reply": "SYNTHETIC: rebound to current objects",
            }
            generated = [row["pid"] for row in server.history]
            server.stop()
            server.start()
            _request(a, "POST", shared_path + "/commands/resubmit", resubmit)
            ready = _wait_for(b, precheck_path, {"ready"})
            assert ready["binding"]["references"]["worker_id"] == "worker-p13-normal"
            assert ready["binding"]["references"]["area_id"] == "area-p13-normal"
            assert ready["evidence"]["citation_ids"]

            completion = {
                "request_id": uuid4().hex,
                "expected_application_version": 4,
                "expected_material_revision": 1,
                "expected_binding_revision": 2,
                "expected_check_id": ready["check_id"],
                "applied_knowledge_citation_ids": ready["evidence"]["citation_ids"],
                "conclusion": "SYNTHETIC: human selected current citations",
            }
            server.stop()
            server.start()
            completed = _request(
                b, "POST", shared_path + "/commands/complete_review", completion
            )
            assert completed["application"]["status"] == "review_completed"
            assert completed["application"]["version"] == 5
            assert completed["application"]["completed_material_revision"] == 1
            report["precheck_blocked_worker"] = "worker-p13-alert"
            report["precheck_blocked_area"] = "area-p13-restricted"
            report["precheck_ready_binding_revision"] = 2
            report["precheck_check_id"] = ready["check_id"]
            report["application_version"] = 5

            event = _request(
                b,
                "POST",
                f"/console/api/tasks/{task}/events",
                {
                    "request_id": uuid4().hex,
                    "expected_revision": 1,
                    "kind": "gas_abnormal",
                },
            )
            assert event["binding"]["object_ref"] == "area-p13-normal"
            assert event["binding"]["binding_revision"] == 2
            assert event["raw"]["alarm_state"] == "active"
            review = _request(
                b,
                "POST",
                f"/console/api/events/{event['receipt_id']}/reviews",
                {"request_id": uuid4().hex},
            )
            assert review["result"]["status"] == "completed"
            assert _request(b, "GET", f"/reviews/{review['review_id']}")[
                "currentness"
            ] == "current"
            report["event_review"] = {
                "binding_revision": 2,
                "area_id": "area-p13-normal",
                "alarm_state": "active",
                "currentness": "current",
            }
            report["task_id"] = task
            report["status"] = "passed"
            report["process_ids"] = generated + [
                row["pid"] for row in server.history if row["pid"] not in generated
            ]
            report["module_files"] = [row["module_file"] for row in server.history]
    finally:
        server.stop()
        stopped = all(row.get("exit_verified") for row in server.history)
        report["directory_cleanup_attempts"] = HARNESS.cleanup_directory(
            directory, processes_stopped=stopped
        )
    report["process_lifecycle"] = server.history
    report["temporary_directory_removed"] = not directory.exists()
    if not report["temporary_directory_removed"]:
        raise RuntimeError("Owned wheel temporary directory was not removed")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = new_output(args.output)
        dsn = os.environ["ANLAN_TEST_DATABASE_URL"]
        report = verify(args.wheel, args.config, dsn)
    except ValueError as error:
        parser.error(str(error))
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({
        "status": report["status"],
        "processes": len(report["process_lifecycle"]),
        "credentials_recorded": False,
    }))


if __name__ == "__main__":
    main()
