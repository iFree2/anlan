import json
import os
import subprocess
import sys

import pytest
from test_events import NOW, OWNER
from test_events_postgres import run
from test_material_revisions import COMPLETE, PATCH
from test_perception_postgres import REFS, prepared


@pytest.mark.postgres
def test_material_revise_and_perception_cli_roundtrip(tmp_path):
    from anlan.interfaces.runtime import postgres_service
    from anlan.workflows.material_analysis import OfflineAnalyzer

    dsn = os.environ["ANLAN_TEST_DATABASE_URL"]

    async def task():
        async with postgres_service(dsn, OfflineAnalyzer()) as service:
            return await service.start(OWNER, COMPLETE)

    original = run(task())
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps(PATCH), encoding="utf-8")
    env = os.environ | {"ANLAN_DATABASE_URL": dsn, "PYTHONIOENCODING": "utf-8"}
    command = [
        sys.executable,
        "-m",
        "anlan",
        "revise",
        "--tenant",
        OWNER.tenant_id,
        "--user",
        OWNER.user_id,
        "--task",
        original["task_id"],
        "--revision",
        "1",
        "--request-id",
        "cli-change",
        "--fields-file",
        str(patch),
    ]
    revised = subprocess.run(command, capture_output=True, encoding="utf-8", env=env, timeout=30)
    assert revised.returncode == 0, revised.stderr
    assert json.loads(revised.stdout)["revision"] == 2
    runtime, _, _, _, event = run(prepared(dsn))
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps(REFS), encoding="utf-8")

    def cli(*args):
        response = subprocess.run(
            [
                sys.executable,
                "-m",
                "anlan.interfaces.perception_cli",
                "--tenant",
                OWNER.tenant_id,
                "--user",
                OWNER.user_id,
                "--as-of",
                NOW.isoformat(),
                *map(str, args),
            ],
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=50,
        )
        assert response.returncode == 0, response.stderr
        return json.loads(response.stdout)

    value = cli("review", event["receipt_id"], "--refs-file", refs, "--request-id", "cli-review")
    assert value["result"]["status"] == "completed"
    assert cli("show", value["review_id"])["result"] == value["result"]
    feedback = cli(
        "feedback",
        value["review_id"],
        "--revision",
        "1",
        "--request-id",
        "feedback",
        "--decision",
        "needs_verification",
    )
    assert feedback["revision"] == 2
    assert run(runtime.get(OWNER, value["review_id"])) == feedback
