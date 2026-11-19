"""Independent host-admin boundary and transactional dynamic MCP registry.

No network clients, business calls, or ordinary Bearer authentication live here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from anlan.infrastructure.db import conninfo
from anlan.tools.dynamic_mcp.contracts import Registration

ADMIN_ACTIONS = frozenset(
    {
        "schema_initialize",
        "register",
        "replace",
        "discover",
        "enable",
        "disable",
        "refresh",
        "inspect",
        "reconcile",
    }
)


class RegistryError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class AdminPrincipal:
    subject: str
    tenant_ids: frozenset[str]
    actions: frozenset[str]
    policy_version: str


@dataclass(frozen=True)
class AdminPolicy:
    subject: str
    tenant_ids: frozenset[str]
    actions: frozenset[str]
    policy_version: str
    token_sha256: str
    purpose: str = "dynamic_mcp_admin"

    def authenticate(self, token):
        if (
            self.purpose != "dynamic_mcp_admin"
            or not isinstance(token, str)
            or not re.fullmatch(r"mcpadm_[0-9a-f]{64}", token)
            or not hmac.compare_digest(
                hashlib.sha256(token.encode()).hexdigest(), self.token_sha256
            )
        ):
            raise RegistryError("access_denied")
        return AdminPrincipal(
            self.subject, frozenset(self.tenant_ids), frozenset(self.actions), self.policy_version
        )

    def authorize(self, admin, tenant, action):
        if (
            type(admin) is not AdminPrincipal
            or admin.subject != self.subject
            or self.purpose != "dynamic_mcp_admin"
            or admin.policy_version != self.policy_version
            or admin.tenant_ids != frozenset(self.tenant_ids)
            or admin.actions != frozenset(self.actions)
            or action not in ADMIN_ACTIONS
            or action not in self.actions
            or (tenant is not None and tenant not in self.tenant_ids)
        ):
            raise RegistryError("access_denied")


@dataclass(frozen=True)
class ManagedRegistration:
    registration: Registration
    owner_subject: str
    reader_user_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandReceipt:
    command_id: str
    action: str
    generation: int
    status: str
    error_code: str | None = None


class DynamicMcpRegistry:
    def __init__(self, dsn, admin_authorizer, clock=None, enable_validator=None):
        self.dsn = dsn
        self.enable_validator = enable_validator
        self.admin_authorizer = admin_authorizer
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def authorize(self, admin, tenant, action):
        self.admin_authorizer.authorize(admin, tenant, action)

    @asynccontextmanager
    async def _connection(self):
        try:
            async with await psycopg.AsyncConnection.connect(
                conninfo(self.dsn), row_factory=dict_row
            ) as conn:
                yield conn
        except RegistryError:
            raise
        except psycopg.Error:
            raise RegistryError("storage_unavailable") from None

    async def initialize(self, admin):
        self.authorize(admin, None, "schema_initialize")
        sql = (Path(__file__).parents[2] / "sql" / "022_dynamic_mcp.sql").read_text(
            encoding="utf-8-sig"
        )
        fingerprint = hashlib.sha256(sql.encode()).hexdigest()
        async with self._connection() as conn:
            await self._lock(conn, "migration:dynamic-mcp:22")
            row = await (
                await conn.execute(
                    (
                        "SELECT EXISTS(SELECT 1 FROM anlan_v2.anlan_schema_migrations WHERE "
                        "version=22) AS present"
                    )
                )
            ).fetchone()
            if row["present"]:
                shape = await (
                    await conn.execute(
                        "SELECT obj_description('anlan_v2.dynamic_mcp_heads'::regclass) AS hash"
                    )
                ).fetchone()
                if shape["hash"] != fingerprint:
                    raise RegistryError("invalid_configuration")
                return
            exists = await (
                await conn.execute(
                    (
                        "SELECT count(*) AS n FROM information_schema.tables WHERE "
                        "table_schema='anlan_v2' AND table_name LIKE 'dynamic_mcp_%'"
                    )
                )
            ).fetchone()
            if exists["n"]:
                raise RegistryError("invalid_configuration")
            await conn.execute(sql)
            from psycopg import sql as sql_builder

            await conn.execute(
                sql_builder.SQL("COMMENT ON TABLE anlan_v2.dynamic_mcp_heads IS {}").format(
                    sql_builder.Literal(fingerprint)
                )
            )

    async def _lock(self, conn, key):
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))

    async def _head(self, conn, tenant, service, expected=None):
        row = await (
            await conn.execute(
                "SELECT * FROM anlan_v2.dynamic_mcp_heads "
                "WHERE tenant_id=%s AND service_id=%s FOR UPDATE",
                (tenant, service),
            )
        ).fetchone()
        if row is None:
            raise RegistryError("access_denied")
        if expected is not None and row["generation"] != expected:
            raise RegistryError("version_conflict")
        return row

    async def _command(self, conn, admin, tenant, command, action, payload):
        if not isinstance(command, str) or not command or len(command) > 200:
            raise RegistryError("invalid_configuration")
        await self._lock(conn, canonical(["command", tenant, admin.subject, command]))
        for table in ("commands", "operations"):
            row = await (
                await conn.execute(
                    f"SELECT * FROM anlan_v2.dynamic_mcp_{table} "
                    "WHERE tenant_id=%s AND admin_subject=%s AND command_id=%s",
                    (tenant, admin.subject, command),
                )
            ).fetchone()
            if row:
                if row["action"] != action or row["payload_hash"] != digest(payload):
                    raise RegistryError("idempotency_conflict")
                if table == "commands":
                    return CommandReceipt(**row["result_json"])
                raise RegistryError(
                    "in_progress" if row["status"] == "reserved" else "outcome_unknown"
                )
        return None

    async def _receipt(
        self,
        conn,
        admin,
        tenant,
        service,
        command,
        action,
        payload,
        expected,
        generation,
        status="completed",
        error=None,
    ):
        result = CommandReceipt(command, action, generation, status, error)
        await conn.execute(
            (
                "INSERT INTO anlan_v2.dynamic_mcp_commands (tenant_id,admin_subject,com"
                "mand_id,service_id,action,payload_hash,expected_generation,result_json"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            (
                tenant,
                admin.subject,
                command,
                service,
                action,
                digest(payload),
                expected,
                Jsonb(asdict(result)),
            ),
        )
        return result

    async def _revision(self, conn, admin, managed, revision):
        reg = managed.registration.model_dump(mode="json")
        if (
            managed.registration.state != "registered"
            or managed.owner_subject != admin.subject
            or len(canonical(reg).encode()) > 65536
        ):
            raise RegistryError("invalid_configuration")
        await conn.execute(
            (
                "INSERT INTO anlan_v2.dynamic_mcp_revisions (tenant_id,service_id,confi"
                "g_revision,registration_json,owner_subject,reader_user_ids,config_hash"
                ",created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            (
                reg["tenant_id"],
                reg["service_id"],
                revision,
                Jsonb(reg),
                managed.owner_subject,
                Jsonb(list(managed.reader_user_ids)),
                digest(reg),
                admin.subject,
            ),
        )

    @staticmethod
    def _freeze_managed(managed):
        try:
            registration = Registration.model_validate_json(managed.registration.model_dump_json())
            readers = tuple(managed.reader_user_ids)
            if (
                len(readers) > 1000
                or len(set(readers)) != len(readers)
                or any(not isinstance(x, str) or not x or len(x) > 300 for x in readers)
                or not isinstance(managed.owner_subject, str)
                or not managed.owner_subject
            ):
                raise ValueError
            return ManagedRegistration(registration, managed.owner_subject, readers)
        except (ValueError, TypeError, AttributeError):
            raise RegistryError("invalid_configuration") from None

    async def register(self, admin, managed, command_id, expected_generation=0):
        managed = self._freeze_managed(managed)
        reg = managed.registration
        self.authorize(admin, reg.tenant_id, "register")
        payload = {
            "managed": asdict(managed) | {"registration": reg.model_dump(mode="json")},
            "expected": expected_generation,
        }
        async with self._connection() as conn:
            old = await self._command(conn, admin, reg.tenant_id, command_id, "register", payload)
            if old:
                return old
            await self._lock(conn, canonical(["head", reg.tenant_id, reg.service_id]))
            exists = await (
                await conn.execute(
                    "SELECT 1 FROM anlan_v2.dynamic_mcp_heads WHERE tenant_id=%s AND service_id=%s",
                    (reg.tenant_id, reg.service_id),
                )
            ).fetchone()
            if exists or expected_generation != 0:
                raise RegistryError("version_conflict")
            await self._revision(conn, admin, managed, 1)
            await conn.execute(
                (
                    "INSERT INTO anlan_v2.dynamic_mcp_heads (tenant_id,service_id,generatio"
                    "n,config_revision,state,target_policy_version) VALUES "
                    "(%s,%s,1,1,'registered',%s)"
                ),
                (reg.tenant_id, reg.service_id, admin.policy_version),
            )
            return await self._receipt(
                conn, admin, reg.tenant_id, reg.service_id, command_id, "register", payload, 0, 1
            )

    async def replace(self, admin, tenant_id, service_id, managed, expected_generation, command_id):
        return await self._change(
            admin,
            tenant_id,
            service_id,
            expected_generation,
            command_id,
            "replace",
            managed=managed,
        )

    async def disable(self, admin, tenant_id, service_id, expected_generation, command_id):
        return await self._change(
            admin, tenant_id, service_id, expected_generation, command_id, "disable"
        )

    async def refresh(self, admin, tenant_id, service_id, expected_generation, command_id):
        return await self._change(
            admin, tenant_id, service_id, expected_generation, command_id, "refresh"
        )

    async def _change(self, admin, tenant, service, expected, command, action, managed=None):
        self.authorize(admin, tenant, action)
        if managed is not None:
            managed = self._freeze_managed(managed)
        payload = {
            "service": service,
            "expected": expected,
            "managed": None
            if managed is None
            else {
                "registration": managed.registration.model_dump(mode="json"),
                "owner_subject": managed.owner_subject,
                "reader_user_ids": managed.reader_user_ids,
            },
        }
        async with self._connection() as conn:
            old = await self._command(conn, admin, tenant, command, action, payload)
            if old:
                return old
            head = await self._head(conn, tenant, service, expected)
            revision = head["config_revision"]
            if managed:
                if (managed.registration.tenant_id, managed.registration.service_id) != (
                    tenant,
                    service,
                ):
                    raise RegistryError("invalid_configuration")
                revision += 1
                await self._revision(conn, admin, managed, revision)
            state = "disabled" if action == "disable" else "registered"
            await conn.execute(
                (
                    "UPDATE anlan_v2.dynamic_mcp_heads SET generation=generation+1,config_r"
                    "evision=%s,state=%s,discovery_id=NULL,validation_digest=NULL,target_po"
                    "licy_version=%s,updated_at=now() WHERE tenant_id=%s AND service_id=%s"
                ),
                (revision, state, admin.policy_version, tenant, service),
            )
            await conn.execute(
                "SELECT pg_notify('dynamic_mcp_revoked',%s)", (digest([tenant, service]),)
            )
            return await self._receipt(
                conn, admin, tenant, service, command, action, payload, expected, expected + 1
            )

    async def get(self, admin, tenant_id, service_id):
        self.authorize(admin, tenant_id, "inspect")
        async with self._connection() as conn:
            head = await self._head(conn, tenant_id, service_id)
            revision = await (
                await conn.execute(
                    (
                        "SELECT * FROM anlan_v2.dynamic_mcp_revisions WHERE tenant_id=%s AND "
                        "service_id=%s AND config_revision=%s"
                    ),
                    (tenant_id, service_id, head["config_revision"]),
                )
            ).fetchone()
            return {
                "head": head,
                "revision": revision,
                "diagnostic": await self._diagnostic(conn, tenant_id, service_id),
            }

    async def list(self, admin, tenant_id, limit=100, cursor=None):
        self.authorize(admin, tenant_id, "inspect")
        if not 1 <= limit <= 100:
            raise RegistryError("invalid_configuration")
        async with self._connection() as conn:
            rows = await (
                await conn.execute(
                    (
                        "SELECT * FROM anlan_v2.dynamic_mcp_heads WHERE tenant_id=%s AND "
                        "service_id>%s ORDER BY service_id LIMIT %s"
                    ),
                    (tenant_id, cursor or "", limit),
                )
            ).fetchall()

            for row in rows:
                row["diagnostic"] = await self._diagnostic(conn, tenant_id, row["service_id"])
            return rows

    async def _diagnostic(self, conn, tenant, service):
        row = await (
            await conn.execute(
                "SELECT jsonb_array_length(tools_json) AS tool_count,status,validation_json "
                "FROM anlan_v2.dynamic_mcp_discoveries WHERE tenant_id=%s AND service_id=%s "
                "ORDER BY created_at DESC,discovery_id DESC LIMIT 1",
                (tenant, service),
            )
        ).fetchone()
        command = await (
            await conn.execute(
                "SELECT result_json FROM anlan_v2.dynamic_mcp_commands "
                "WHERE tenant_id=%s AND service_id=%s "
                "ORDER BY created_at DESC,command_id DESC LIMIT 1",
                (tenant, service),
            )
        ).fetchone()
        errors = list(row["validation_json"].get("error_codes", [])) if row else []
        error = command["result_json"].get("error_code") if command else None
        if error and error not in errors:
            errors.append(error)
        return {
            "tool_count": row["tool_count"] if row else 0,
            "validation_status": row["status"] if row else "not_discovered",
            "error_codes": errors,
        }

    async def reserve_discovery(
        self,
        admin,
        tenant_id,
        service_id,
        expected_generation,
        command_id,
        credential_generation="",
        deadline_seconds=20,
    ):
        from anlan.tools.dynamic_mcp.catalog import CatalogLease

        self.authorize(admin, tenant_id, "discover")
        payload = {"service": service_id, "expected": expected_generation}
        async with self._connection() as conn:
            old = await self._command(conn, admin, tenant_id, command_id, "discover", payload)
            if old:
                if old.status == "outcome_unknown":
                    raise RegistryError("outcome_unknown")
                return old
            head = await self._head(conn, tenant_id, service_id, expected_generation)
            if (
                head["state"] not in ("registered", "discovered")
                or head["target_policy_version"] != admin.policy_version
            ):
                raise RegistryError("stale_generation")
            lease = CatalogLease(
                tenant_id=tenant_id,
                service_id=service_id,
                generation=expected_generation,
                config_revision=head["config_revision"],
                discovery_id=head["discovery_id"],
                target_policy_version=admin.policy_version,
                credential_generation=credential_generation,
            )
            await conn.execute(
                (
                    "INSERT INTO anlan_v2.dynamic_mcp_operations (tenant_id,admin_subject,c"
                    "ommand_id,service_id,action,payload_hash,lease_json,status,deadline_at"
                    ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                ),
                (
                    tenant_id,
                    admin.subject,
                    command_id,
                    service_id,
                    "discover",
                    digest(payload),
                    Jsonb(lease.model_dump(mode="json")),
                    "reserved",
                    self.clock() + timedelta(seconds=deadline_seconds),
                ),
            )
            return lease

    async def reconcile(self, admin, tenant_id, command_id, expected_operation_status="reserved"):
        self.authorize(admin, tenant_id, "reconcile")
        async with self._connection() as conn:
            await self._lock(conn, canonical(["command", tenant_id, admin.subject, command_id]))
            op = await (
                await conn.execute(
                    (
                        "SELECT * FROM anlan_v2.dynamic_mcp_operations WHERE tenant_id=%s AND "
                        "admin_subject=%s AND command_id=%s FOR UPDATE"
                    ),
                    (tenant_id, admin.subject, command_id),
                )
            ).fetchone()
            if not op:
                raise RegistryError("access_denied")
            prior = await (
                await conn.execute(
                    (
                        "SELECT result_json FROM anlan_v2.dynamic_mcp_commands WHERE "
                        "tenant_id=%s AND admin_subject=%s AND command_id=%s"
                    ),
                    (tenant_id, admin.subject, command_id),
                )
            ).fetchone()
            if prior:
                return CommandReceipt(**prior["result_json"])
            if op["status"] != expected_operation_status or op["deadline_at"] > self.clock():
                raise RegistryError("in_progress")
            lease = op["lease_json"]
            result = CommandReceipt(
                command_id, op["action"], lease["generation"], "outcome_unknown", "outcome_unknown"
            )
            await conn.execute(
                (
                    "INSERT INTO anlan_v2.dynamic_mcp_commands (tenant_id,admin_subject,com"
                    "mand_id,service_id,action,payload_hash,expected_generation,result_json"
                    ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                ),
                (
                    tenant_id,
                    admin.subject,
                    command_id,
                    op["service_id"],
                    op["action"],
                    op["payload_hash"],
                    lease["generation"],
                    Jsonb(asdict(result)),
                ),
            )
            await conn.execute(
                (
                    "UPDATE anlan_v2.dynamic_mcp_operations SET status='outcome_unknown' "
                    "WHERE tenant_id=%s AND admin_subject=%s AND command_id=%s"
                ),
                (tenant_id, admin.subject, command_id),
            )
            return result

    async def assert_current(self, lease):
        async with self._connection() as conn:
            head = await self._head(conn, lease.tenant_id, lease.service_id)
            if head["state"] == "disabled" or any(
                head[k] != getattr(lease, k)
                for k in ("generation", "config_revision", "target_policy_version", "discovery_id")
            ):
                raise RegistryError("stale_generation")

    async def record_discovery(self, admin, lease, discovery, command_id):
        from anlan.tools.dynamic_mcp.catalog import (
            DiscoverySnapshot,
            make_discovery,
            validate_discovery,
        )

        tenant, service = lease.tenant_id, lease.service_id
        self.authorize(admin, tenant, "discover")
        # Reconstruct at the storage boundary: model_copy/construct cannot bypass sanitization.
        try:
            snapshot = DiscoverySnapshot.model_validate(discovery.model_dump(mode="json"))
            rebuilt = make_discovery(
                **(snapshot.model_dump(exclude={"digest", "tools"}) | {"tools": snapshot.tools})
            )
            if (
                snapshot.digest != rebuilt.digest
                or snapshot.captured_generation != lease.generation
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise RegistryError("invalid_configuration") from None
        async with self._connection() as conn:
            await self._lock(conn, canonical(["command", tenant, admin.subject, command_id]))
            op = await (
                await conn.execute(
                    (
                        "SELECT * FROM anlan_v2.dynamic_mcp_operations WHERE tenant_id=%s AND "
                        "admin_subject=%s AND command_id=%s FOR UPDATE"
                    ),
                    (tenant, admin.subject, command_id),
                )
            ).fetchone()
            if not op or op["lease_json"] != lease.model_dump(mode="json"):
                raise RegistryError("access_denied")
            previous = await (
                await conn.execute(
                    (
                        "SELECT result_json FROM anlan_v2.dynamic_mcp_commands WHERE "
                        "tenant_id=%s AND admin_subject=%s AND command_id=%s"
                    ),
                    (tenant, admin.subject, command_id),
                )
            ).fetchone()
            if previous:
                return CommandReceipt(**previous["result_json"])
            if op["status"] != "reserved":
                raise RegistryError("outcome_unknown")
            head = await self._head(conn, tenant, service)
            stale = (
                head["state"] not in {"registered", "discovered"}
                or head["generation"] != lease.generation
                or head["config_revision"] != lease.config_revision
                or head["target_policy_version"] != lease.target_policy_version
                or admin.policy_version != lease.target_policy_version
            )
            error = "stale_generation" if stale else None
            generation = head["generation"]
            if not stale:
                row = await (
                    await conn.execute(
                        (
                            "SELECT registration_json FROM anlan_v2.dynamic_mcp_revisions WHERE "
                            "tenant_id=%s AND service_id=%s AND config_revision=%s"
                        ),
                        (tenant, service, lease.config_revision),
                    )
                ).fetchone()
                report = validate_discovery(
                    Registration.model_validate(row["registration_json"]), snapshot
                )
                state = "validated" if report.valid else "discovered"
                tools = [t.model_dump(mode="json") for t in snapshot.tools]
                await conn.execute(
                    (
                        "INSERT INTO anlan_v2.dynamic_mcp_discoveries (tenant_id,service_id,dis"
                        "covery_id,config_revision,captured_generation,tools_json,protocol_vers"
                        "ion,server_name,server_version,schema_profile,snapshot_hash,validation"
                        "_json,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                    ),
                    (
                        tenant,
                        service,
                        snapshot.discovery_id,
                        lease.config_revision,
                        lease.generation,
                        Jsonb(tools),
                        snapshot.protocol_version,
                        snapshot.server_name,
                        snapshot.server_version,
                        report.schema_profile,
                        snapshot.digest,
                        Jsonb(report.model_dump(mode="json")),
                        state,
                    ),
                )
                generation += 1
                await conn.execute(
                    (
                        "UPDATE anlan_v2.dynamic_mcp_heads SET generation=%s,state=%s,discovery"
                        "_id=%s,validation_digest=%s,credential_generation=%s,updated_at=now() "
                        "WHERE tenant_id=%s AND service_id=%s"
                    ),
                    (
                        generation,
                        state,
                        snapshot.discovery_id,
                        report.digest if report.valid else None,
                        lease.credential_generation,
                        tenant,
                        service,
                    ),
                )
                if not report.valid:
                    error = report.error_codes[0]
            self.authorize(admin, tenant, "discover")
            payload = {"service": service, "expected": lease.generation}
            receipt = await self._receipt(
                conn,
                admin,
                tenant,
                service,
                command_id,
                "discover",
                payload,
                lease.generation,
                generation,
                status="failed" if error else "completed",
                error=error,
            )
            await conn.execute(
                (
                    "UPDATE anlan_v2.dynamic_mcp_operations SET status='completed' WHERE "
                    "tenant_id=%s AND admin_subject=%s AND command_id=%s"
                ),
                (tenant, admin.subject, command_id),
            )
            return receipt

    async def enable(
        self, admin, tenant_id, service_id, expected_generation, validation_digest, command_id
    ):
        self.authorize(admin, tenant_id, "enable")
        payload = {
            "service": service_id,
            "expected": expected_generation,
            "validation_digest": validation_digest,
        }
        async with self._connection() as conn:
            old = await self._command(conn, admin, tenant_id, command_id, "enable", payload)
            if old:
                return old
            # Read scope without taking the head lock. Scope locks must precede head locks.
            row = await (
                await conn.execute(
                    (
                        "SELECT h.generation,h.config_revision,r.registration_json "
                        "FROM anlan_v2.dynamic_mcp_heads h JOIN "
                        "anlan_v2.dynamic_mcp_revisions r "
                        "USING(tenant_id,service_id,config_revision) WHERE h.tenant_id=%s AND "
                        "h.service_id=%s"
                    ),
                    (tenant_id, service_id),
                )
            ).fetchone()
            if not row:
                raise RegistryError("access_denied")
            registration = Registration.model_validate(row["registration_json"])
            scopes = sorted(
                {(tenant_id, b.capability, f) for b in registration.bindings for f in b.factory_ids}
            )
            for scope in scopes:
                await self._lock(conn, canonical(["source", *scope]))
            head = await self._head(conn, tenant_id, service_id, expected_generation)
            if (
                head["generation"] != row["generation"]
                or head["config_revision"] != row["config_revision"]
            ):
                raise RegistryError("version_conflict")
            if (
                head["state"] != "validated"
                or not head["discovery_id"]
                or head["validation_digest"] != validation_digest
                or head["target_policy_version"] != admin.policy_version
            ):
                raise RegistryError("stale_generation")
            from anlan.tools.dynamic_mcp.catalog import ValidationReport

            report_row = await (
                await conn.execute(
                    (
                        "SELECT validation_json,config_revision FROM "
                        "anlan_v2.dynamic_mcp_discoveries WHERE tenant_id=%s AND service_id=%s "
                        "AND discovery_id=%s"
                    ),
                    (tenant_id, service_id, head["discovery_id"]),
                )
            ).fetchone()
            report = ValidationReport.model_validate(report_row["validation_json"])
            if (
                not report.valid
                or report.registration_digest != digest(registration.model_dump(mode="json"))
                or report.digest != validation_digest
                or report_row["config_revision"] != head["config_revision"]
            ):
                raise RegistryError("contract_mismatch")
            if self.enable_validator is None:
                raise RegistryError("target_not_allowed")
            await self.enable_validator(admin, registration, head["credential_generation"])
            competitors = await (
                await conn.execute(
                    (
                        "SELECT r.registration_json FROM anlan_v2.dynamic_mcp_heads h JOIN "
                        "anlan_v2.dynamic_mcp_revisions r "
                        "USING(tenant_id,service_id,config_revision) WHERE h.tenant_id=%s AND "
                        "h.service_id<>%s AND h.state='enabled'"
                    ),
                    (tenant_id, service_id),
                )
            ).fetchall()
            for other in competitors:
                reg = Registration.model_validate(other["registration_json"])
                if set(scopes) & {
                    (tenant_id, b.capability, f) for b in reg.bindings for f in b.factory_ids
                }:
                    raise RegistryError("source_conflict")
            self.authorize(admin, tenant_id, "enable")
            await conn.execute(
                (
                    "UPDATE anlan_v2.dynamic_mcp_heads SET "
                    "state='enabled',generation=generation+1,updated_at=now() WHERE "
                    "tenant_id=%s AND service_id=%s"
                ),
                (tenant_id, service_id),
            )
            return await self._receipt(
                conn,
                admin,
                tenant_id,
                service_id,
                command_id,
                "enable",
                payload,
                expected_generation,
                expected_generation + 1,
            )

    async def load_catalog(self, scope):
        from anlan.tools.dynamic_mcp.catalog import CatalogSource, ValidationReport, build_catalog

        async with self._connection() as conn:
            rows = await (
                await conn.execute(
                    (
                        "SELECT h.*,r.registration_json,r.reader_user_ids,d.validation_json "
                        "FROM anlan_v2.dynamic_mcp_heads h JOIN anlan_v2.dynamic_mcp_revisions "
                        "r USING(tenant_id,service_id,config_revision) JOIN "
                        "anlan_v2.dynamic_mcp_discoveries d ON (h.tenant_id=d.tenant_id AND "
                        "h.service_id=d.service_id AND h.discovery_id=d.discovery_id) WHERE "
                        "h.tenant_id=%s AND h.state='enabled'"
                    ),
                    (scope.identity.tenant_id,),
                )
            ).fetchall()
            sources = []
            reports = {}
            for row in rows:
                sources.append(
                    CatalogSource(
                        **{
                            k: row[k]
                            for k in [
                                "tenant_id",
                                "service_id",
                                "config_revision",
                                "generation",
                                "state",
                                "discovery_id",
                                "validation_digest",
                            ]
                        },
                        reader_user_ids=tuple(row["reader_user_ids"]),
                        registration_json=canonical(row["registration_json"]),
                        target_policy_version=row["target_policy_version"],
                        reader_grant_version=str(row["config_revision"]),
                    )
                )
                reports[row["discovery_id"]] = ValidationReport.model_validate(
                    row["validation_json"]
                )
            return build_catalog(scope, sources, reports)

    async def fail_discovery(self, admin, lease, command_id, error_code):
        self.authorize(admin, lease.tenant_id, "discover")
        allowed = {
            "outcome_unknown",
            "unsupported_target",
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
            "stale_generation",
            "cleanup_failed",
            "storage_unavailable",
            "access_denied",
        }
        if error_code not in allowed:
            raise RegistryError("invalid_configuration")
        tenant, service = lease.tenant_id, lease.service_id
        async with self._connection() as conn:
            await self._lock(conn, canonical(["command", tenant, admin.subject, command_id]))
            op = await (
                await conn.execute(
                    "SELECT * FROM anlan_v2.dynamic_mcp_operations "
                    "WHERE tenant_id=%s AND admin_subject=%s AND command_id=%s FOR UPDATE",
                    (tenant, admin.subject, command_id),
                )
            ).fetchone()
            if not op or op["lease_json"] != lease.model_dump(mode="json"):
                raise RegistryError("access_denied")
            old = await (
                await conn.execute(
                    "SELECT result_json FROM anlan_v2.dynamic_mcp_commands "
                    "WHERE tenant_id=%s AND admin_subject=%s AND command_id=%s",
                    (tenant, admin.subject, command_id),
                )
            ).fetchone()
            if old:
                return CommandReceipt(**old["result_json"])
            if op["status"] != "reserved":
                raise RegistryError("outcome_unknown")
            unknown = error_code in {"outcome_unknown", "storage_unavailable"}
            status = "outcome_unknown" if unknown else "failed"
            receipt = await self._receipt(
                conn,
                admin,
                tenant,
                service,
                command_id,
                "discover",
                {"service": service, "expected": lease.generation},
                lease.generation,
                lease.generation,
                status=status,
                error="outcome_unknown" if unknown else error_code,
            )
            await conn.execute(
                "UPDATE anlan_v2.dynamic_mcp_operations SET status=%s "
                "WHERE tenant_id=%s AND admin_subject=%s AND command_id=%s",
                ("outcome_unknown" if unknown else "completed", tenant, admin.subject, command_id),
            )
            return receipt

    async def _business_current(self, conn, identity, lease):
        """Business readers never borrow the independent administrator boundary."""
        from anlan.common.models import Identity

        if type(identity) is not Identity or identity.tenant_id != lease.tenant_id:
            raise RegistryError("access_denied")
        row = await (
            await conn.execute(
                "SELECT h.*,r.registration_json,r.reader_user_ids,d.validation_json "
                "FROM anlan_v2.dynamic_mcp_heads h JOIN anlan_v2.dynamic_mcp_revisions r "
                "USING(tenant_id,service_id,config_revision) "
                "LEFT JOIN anlan_v2.dynamic_mcp_discoveries d "
                "ON (h.tenant_id=d.tenant_id AND h.service_id=d.service_id "
                "AND h.discovery_id=d.discovery_id) WHERE h.tenant_id=%s AND h.service_id=%s "
                "FOR SHARE OF h",
                (identity.tenant_id, lease.service_id),
            )
        ).fetchone()
        if row is None or identity.user_id not in row["reader_user_ids"]:
            raise RegistryError("access_denied")
        if row["state"] != "enabled" or any(
            row[k] != getattr(lease, k)
            for k in (
                "generation",
                "config_revision",
                "discovery_id",
                "target_policy_version",
                "credential_generation",
            )
        ):
            raise RegistryError("stale_generation")
        return row

    async def resolve_business(self, identity, entry):
        from anlan.common.models import Identity
        from anlan.tools.dynamic_mcp.catalog import CatalogEntry, CatalogLease, ValidationReport

        if type(identity) is not Identity or identity.tenant_id != entry.tenant_id:
            raise RegistryError("access_denied")
        entry = CatalogEntry.model_validate_json(entry.model_dump_json())
        async with self._connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT target_policy_version,credential_generation FROM "
                    "anlan_v2.dynamic_mcp_heads WHERE tenant_id=%s AND service_id=%s",
                    (identity.tenant_id, entry.service_id),
                )
            ).fetchone()
            if row is None:
                raise RegistryError("access_denied")
            lease = CatalogLease(
                **entry.model_dump(
                    include={
                        "tenant_id",
                        "service_id",
                        "generation",
                        "config_revision",
                        "discovery_id",
                    }
                ),
                target_policy_version=row["target_policy_version"],
                credential_generation=row["credential_generation"],
            )
            row = await self._business_current(conn, identity, lease)
            report = ValidationReport.model_validate(row["validation_json"])
            if not report.valid or not any(
                t.alias == entry.alias
                and t.original_name == entry.original_name
                and t.capability == entry.capability
                and t.contract_version == entry.contract_version
                for t in report.tools
            ):
                raise RegistryError("access_denied")
            registration = Registration.model_validate(row["registration_json"])
            if not any(
                b.tool_name == entry.original_name
                and b.capability == entry.capability
                and set(entry.factory_ids) <= set(b.factory_ids)
                for b in registration.bindings
            ):
                raise RegistryError("access_denied")
            return registration, lease
