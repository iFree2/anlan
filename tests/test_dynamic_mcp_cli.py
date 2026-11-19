import importlib.util
import subprocess
import sys


def test_cli_has_no_business_call_and_no_self_granted_identity():
    assert importlib.util.find_spec("anlan.interfaces.mcp_registry_cli"), (
        "CLI implementation missing"
    )
    result = subprocess.run(
        [sys.executable, "-m", "anlan.interfaces.mcp_registry_cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "discover" in result.stdout
    assert "diagnose" not in result.stdout
    for args in [
        ["call"],
        ["diagnose"],
        ["--admin"],
        ["--token", "secret"],
        ["--request-file", "x"],
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "anlan.interfaces.mcp_registry_cli", *args],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "secret" not in result.stdout


def test_cli_receipt_exit_mapping_and_redaction():
    assert importlib.util.find_spec("anlan.interfaces.mcp_registry_cli"), (
        "CLI implementation missing"
    )
    from anlan.interfaces.mcp_registry_cli import error_exit_code

    assert error_exit_code("in_progress") == 4
    assert error_exit_code("outcome_unknown") == 5
    assert error_exit_code("unsupported_target") == 5
    result = subprocess.run(
        [sys.executable, "-m", "anlan.interfaces.mcp_registry_cli", "initialize"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3
    assert "access_denied" in result.stdout


def test_cli_pg_register_inspect_and_normal_bearer_rejection(tmp_path):
    import hashlib
    import json
    import os
    import uuid

    from test_dynamic_mcp_registry import api, managed, run, setup

    r, store, admin, tenant = setup()
    run(store.initialize(admin))
    token = "mcpadm_" + "ab" * 32
    policy = tmp_path / "admin.json"
    policy.write_text(
        json.dumps(
            dict(
                purpose="dynamic_mcp_admin",
                subject="host",
                tenant_ids=[tenant],
                actions=sorted(r.ADMIN_ACTIONS),
                policy_version="p1",
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            )
        )
    )
    registration = tmp_path / "registration.json"
    m = managed(api(), tenant, "cli-" + uuid.uuid4().hex[:8])
    registration.write_text(
        json.dumps(
            dict(
                registration=m.registration.model_dump(mode="json"),
                owner_subject="host",
                reader_user_ids=["reader"],
            )
        )
    )
    env = dict(
        os.environ,
        ANLAN_MCP_ADMIN_TOKEN=token,
        ANLAN_MCP_ADMIN_POLICY=str(policy),
        ANLAN_DATABASE_URL=store.dsn,
    )

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "anlan.interfaces.mcp_registry_cli", *args],
            env=env,
            capture_output=True,
            text=True,
        )

    result = cli("register", "--file", str(registration), "--command-id", "cli-register")
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["generation"] == 1
    assert (
        cli("inspect", "--tenant", tenant, "--service", m.registration.service_id).returncode == 0
    )
    env["ANLAN_MCP_ADMIN_TOKEN"] = "ordinary-bearer-secret"
    result = cli("inspect", "--tenant", tenant, "--service", m.registration.service_id)
    assert result.returncode == 3
    assert "ordinary-bearer-secret" not in result.stdout + result.stderr


def test_cli_parser_never_echoes_secret(capsys):
    from anlan.interfaces.mcp_registry_cli import main

    assert main(["--token", "SENTINEL_SECRET"]) == 2
    captured = capsys.readouterr()
    assert "SENTINEL_SECRET" not in captured.out + captured.err
