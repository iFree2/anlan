"""Local host-admin CLI; intentionally separate from ordinary application Bearer auth."""

import argparse
import asyncio
import ipaddress
import json
import os
import selectors
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from anlan.infrastructure.db import database_url
from anlan.tools.dynamic_mcp.contracts import Registration
from anlan.tools.dynamic_mcp.registry import (
    AdminPolicy,
    DynamicMcpRegistry,
    ManagedRegistration,
    RegistryError,
)


def error_exit_code(code):
    if code == "access_denied":
        return 3
    if code in {"in_progress", "version_conflict", "idempotency_conflict", "stale_generation"}:
        return 4
    if code == "invalid_configuration":
        return 2
    if code == "storage_unavailable":
        return 6
    if code == "cleanup_failed":
        return 7
    if code == "cancelled":
        return 130
    return 5


def read_json(path):
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise RegistryError("invalid_configuration")
    return json.loads(raw.decode("utf-8-sig"))


class HostPolicy:
    def __init__(self):
        self.path = os.environ.get("ANLAN_MCP_ADMIN_POLICY", "")
        self.token = os.environ.get("ANLAN_MCP_ADMIN_TOKEN", "")
        self.configuration = self._read()
        self.principal = self._policy(self.configuration).authenticate(self.token)

    def _read(self):
        if not self.path:
            raise RegistryError("access_denied")
        try:
            return read_json(self.path)
        except (ValueError, OSError):
            raise RegistryError("access_denied") from None

    @staticmethod
    def _policy(config):
        try:
            if config["purpose"] != "dynamic_mcp_admin":
                raise KeyError
            return AdminPolicy(
                config["subject"],
                frozenset(config["tenant_ids"]),
                frozenset(config["actions"]),
                config["policy_version"],
                config["token_sha256"],
                config["purpose"],
            )
        except (KeyError, TypeError):
            raise RegistryError("access_denied") from None

    def authorize(self, admin, tenant, action):
        policy = self._policy(self._read())
        if policy.authenticate(self.token) != admin:
            raise RegistryError("access_denied")
        policy.authorize(admin, tenant, action)

    def credential_generation(self, registration):
        ref = registration.connection.credential_ref
        if ref is None:
            return ""
        record = self._read().get("credentials", {}).get(registration.tenant_id, {}).get(ref)
        if not record or not os.environ.get(record["environment_variable"]):
            raise RegistryError("credential_unavailable")
        return str(record["generation"])

    async def validate_enable(self, admin, registration, credential_generation):
        self.authorize(admin, registration.tenant_id, "enable")
        self.validate_target(registration)
        if self.credential_generation(registration) != credential_generation:
            raise RegistryError("credential_unavailable")

    def validate_target(self, registration):
        config = self._read().get("trusted_targets", {})
        connection = registration.connection
        if connection.transport == "stdio":
            profiles = [
                p
                for p in config.get("executable_profiles", [])
                if p["tenant_id"] == registration.tenant_id
                and p["executable_ref"] == connection.executable_ref
            ]
            if len(profiles) != 1:
                raise RegistryError("target_not_allowed")
            p = profiles[0]
            if (
                list(connection.argv) != p["argv"]
                or not Path(p["executable"]).is_absolute()
                or not Path(p["cwd"]).is_absolute()
                or Path(p["executable"]).stem.lower() in {"cmd", "powershell", "pwsh", "sh", "bash"}
                or any(a.lower() in {"-c", "-command", "/c", "-encodedcommand"} for a in p["argv"])
            ):
                raise RegistryError("target_not_allowed")
        else:
            profiles = [
                p
                for p in config.get("http_profiles", [])
                if p["tenant_id"] == registration.tenant_id
                and p["target_ref"] == connection.target_ref
            ]
            if len(profiles) != 1:
                raise RegistryError("target_not_allowed")
            p = profiles[0]
            parsed = urlsplit(p["url"])
            try:
                ipaddress.ip_address(parsed.hostname or "")
                parsed.port
            except ValueError:
                raise RegistryError("unsupported_target") from None
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise RegistryError("target_not_allowed")
            if p.get("synthetic_loopback_http", False):
                if (
                    registration.data_origin != "SYNTHETIC"
                    or parsed.scheme != "http"
                    or parsed.hostname != "127.0.0.1"
                    or parsed.path != "/mcp"
                ):
                    raise RegistryError("target_not_allowed")
            elif parsed.scheme != "https":
                raise RegistryError("target_not_allowed")


def managed_file(path):
    data = read_json(path)
    if set(data) - {"registration", "owner_subject", "reader_user_ids"}:
        raise RegistryError("invalid_configuration")
    raw = data["registration"]
    argv = raw.get("connection", {}).get("argv", [])
    if any(not isinstance(v, str) or v != v.strip() for v in argv):
        raise RegistryError("invalid_configuration")
    readers = data.get("reader_user_ids", [])
    if not isinstance(readers, list) or any(not isinstance(x, str) or not x for x in readers):
        raise RegistryError("invalid_configuration")
    return ManagedRegistration(
        Registration.model_validate(raw), data["owner_subject"], tuple(readers)
    )


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "invalid_configuration\n")


def parser():
    root = QuietParser(description="Trusted local dynamic MCP registration")
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("initialize")
    for action in [
        "register",
        "replace",
        "discover",
        "enable",
        "disable",
        "refresh",
        "inspect",
        "list",
        "reconcile",
    ]:
        p = commands.add_parser(action)
        if action != "register":
            p.add_argument("--tenant", required=True)
        if action not in {"register", "list", "reconcile"}:
            p.add_argument("--service", required=True)
        if action not in {"inspect", "list"}:
            p.add_argument("--command-id", required=True)
        if action not in {"register", "inspect", "list", "reconcile"}:
            p.add_argument("--expected-generation", type=int, required=True)
        if action in {"register", "replace"}:
            p.add_argument("--file", required=True)
        if action == "enable":
            p.add_argument("--validation-digest", required=True)
    return root


def runtime_from_host(host, store):
    from pydantic import SecretStr

    from anlan.tools.dynamic_mcp.runtime import (
        ExecutableProfile,
        HttpProfile,
        RuntimeManager,
        TrustedTargets,
    )

    config = host.configuration.get("trusted_targets", {})
    profiles = []
    for p in config.get("executable_profiles", []):
        profiles.append(
            ExecutableProfile(
                **(p | {"argv": tuple(p["argv"]), "env": tuple(tuple(x) for x in p.get("env", []))})
            )
        )
    http = tuple(HttpProfile(**p) for p in config.get("http_profiles", []))
    targets = TrustedTargets(host.principal.policy_version, tuple(profiles), http)

    class Credentials:
        async def resolve(self, tenant_id, credential_ref):
            record = host._read().get("credentials", {}).get(tenant_id, {}).get(credential_ref)
            if not record or not os.environ.get(record["environment_variable"]):
                raise RegistryError("credential_unavailable")
            return SecretStr(os.environ[record["environment_variable"]]), str(record["generation"])

    return RuntimeManager(targets, Credentials(), store)


async def execute(args):
    host = HostPolicy()
    admin = host.principal
    action = (
        "schema_initialize"
        if args.action == "initialize"
        else ("inspect" if args.action == "list" else args.action)
    )
    host.authorize(admin, getattr(args, "tenant", None), action)
    store = DynamicMcpRegistry(database_url(), host, enable_validator=host.validate_enable)
    if args.action == "initialize":
        await store.initialize(admin)
        return {"status": "completed"}
    if args.action == "register":
        return asdict(await store.register(admin, managed_file(args.file), args.command_id))
    if args.action == "replace":
        return asdict(
            await store.replace(
                admin,
                args.tenant,
                args.service,
                managed_file(args.file),
                args.expected_generation,
                args.command_id,
            )
        )
    if args.action in {"inspect", "list"}:
        data = (
            await store.list(admin, args.tenant)
            if args.action == "list"
            else [
                (lambda result: {**result["head"], "diagnostic": result["diagnostic"]})(
                    await store.get(admin, args.tenant, args.service)
                )
            ]
        )
        return {
            "status": "completed",
            "services": [
                {
                    "service_id": x["service_id"],
                    "generation": x["generation"],
                    "config_revision": x["config_revision"],
                    "state": x["state"],
                    "validation_digest": x["validation_digest"],
                    "discovery_id": x["discovery_id"],
                    "diagnostic": x["diagnostic"],
                }
                for x in data
            ],
        }
    if args.action == "reconcile":
        return asdict(await store.reconcile(admin, args.tenant, args.command_id))
    if args.action == "enable":
        return asdict(
            await store.enable(
                admin,
                args.tenant,
                args.service,
                args.expected_generation,
                args.validation_digest,
                args.command_id,
            )
        )
    if args.action == "disable":
        return asdict(
            await store.disable(
                admin, args.tenant, args.service, args.expected_generation, args.command_id
            )
        )
    generation = args.expected_generation
    if args.action == "refresh":
        revoked = await store.refresh(admin, args.tenant, args.service, generation, args.command_id)
        generation = revoked.generation
    registration = Registration.model_validate(
        (await store.get(admin, args.tenant, args.service))["revision"]["registration_json"]
    )
    host.validate_target(registration)
    credential_generation = host.credential_generation(registration)
    lease = await store.reserve_discovery(
        admin,
        args.tenant,
        args.service,
        generation,
        args.command_id + ":discovery" if args.action == "refresh" else args.command_id,
        credential_generation=credential_generation,
    )
    from anlan.tools.dynamic_mcp.registry import CommandReceipt

    if isinstance(lease, CommandReceipt):
        return asdict(lease)
    registration = Registration.model_validate(
        (await store.get(admin, args.tenant, args.service))["revision"]["registration_json"]
    )
    runtime = runtime_from_host(host, store)
    network_command = (
        args.command_id + ":discovery" if args.action == "refresh" else args.command_id
    )
    try:
        snapshot = await runtime.discover(admin, registration, lease)
        host.authorize(admin, registration.tenant_id, "discover")
        host.validate_target(registration)
        if host.credential_generation(registration) != lease.credential_generation:
            raise RegistryError("credential_unavailable")
        result = await store.record_discovery(
            admin,
            lease,
            snapshot,
            args.command_id + ":discovery" if args.action == "refresh" else args.command_id,
        )
    except Exception as exc:
        error = getattr(exc, "code", "disconnected")
        try:
            result = await store.fail_discovery(admin, lease, network_command, error)
        except RegistryError as storage_error:
            if storage_error.code == "storage_unavailable":
                raise RegistryError("outcome_unknown") from None
            raise
    finally:
        cleanup = await runtime.close()
    if cleanup.status != "closed":
        raise RegistryError("cleanup_failed")
    return asdict(result)


def main(argv=None):
    p = parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return exc.code
    try:
        result = (
            asyncio.run(
                execute(args),
                loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
            )
            if sys.platform == "win32"
            else asyncio.run(execute(args))
        )
        code = error_exit_code(result["error_code"]) if result.get("error_code") else 0
    except KeyboardInterrupt:
        result = {"status": "cancelled", "error_code": "cancelled"}
        code = 130
    except Exception as exc:
        error = getattr(exc, "code", "invalid_configuration")
        # Fixed host-owned categories only; never remote exception text.
        known = {
            "access_denied",
            "in_progress",
            "outcome_unknown",
            "unsupported_target",
            "invalid_configuration",
            "target_not_allowed",
            "credential_unavailable",
            "connect_timeout",
            "initialize_failed",
            "discovery_timeout",
            "discovery_incomplete",
            "schema_unsupported",
            "contract_mismatch",
            "cancelled",
            "disconnected",
            "oversized_result",
            "source_conflict",
            "version_conflict",
            "idempotency_conflict",
            "stale_generation",
            "cleanup_failed",
            "storage_unavailable",
        }
        error = error if error in known else "invalid_configuration"
        result = {"status": error, "error_code": error}
        code = error_exit_code(error)
    print(json.dumps({"schema_version": "mcp-admin-receipt-v1", **result}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
