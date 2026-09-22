"""A receipt is durable across independent CLI processes without any model."""
import json
import os
import subprocess
import sys

import pytest
from test_events import NOW, OWNER, payload
from test_events_postgres import run, setup


@pytest.mark.postgres
def test_receipt_process_show_and_denied_read(tmp_path):
    dsn = os.environ.get("ANLAN_TEST_DATABASE_URL")
    if not dsn:
        pytest.fail("Real PG is required", pytrace=False)
    store, _, config = run(setup(dsn))
    run(store.initialize())
    body = tmp_path / "body.json"
    config_file = tmp_path / "binding.json"
    body.write_text(json.dumps(payload()), encoding="utf-8")
    config_file.write_text(config.model_dump_json(), encoding="utf-8")

    def cli(*args, user=OWNER.user_id, expect=0):
        result = subprocess.run([
            sys.executable, "-m", "anlan.interfaces.events_cli", "--tenant", OWNER.tenant_id,
            "--user", user, "--as-of", NOW.isoformat(), *map(str, args)],
            env=os.environ | {"ANLAN_DATABASE_URL": dsn, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, encoding="utf-8", timeout=30)
        assert result.returncode == expect, result.stderr
        return json.loads(result.stdout) if expect == 0 else result.stderr

    received = cli("receive", "--source", config.source_id, "--body", body,
                   "--binding", config_file)
    receipt_id = received["receipt_id"]
    assert cli("show", receipt_id)["result"] is None
    linked = cli("process", receipt_id)
    assert linked["result"]["status"] == "linked"
    assert cli("receive", "--source", config.source_id, "--body", body,
               "--binding", config_file) == linked
    assert cli("show", receipt_id) == linked
    denied = cli("show", receipt_id, user="stranger", expect=2)
    assert receipt_id not in denied and "postgresql://" not in denied
