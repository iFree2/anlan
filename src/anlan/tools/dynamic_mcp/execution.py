"""Executor-bound business calls; no reusable client/session handle is exported."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, create_model

from anlan.common.models import StrictModel
from anlan.tools.dynamic_mcp.catalog import canonical_schema, expected_schemas, sanitize_tool
from anlan.tools.dynamic_mcp.contracts import (
    Capability,
    CapabilityRequest,
    DynamicEvidence,
    HostReceipt,
    ReceivedEvidence,
    bind_evidence,
)
from anlan.tools.dynamic_mcp.runtime import (
    RuntimeFailure,
    RuntimeManager,
    _business_session,
    _exception_code,
    _maybe_await,
)
from anlan.tools.registry import ToolDefinition, ToolRegistry


class CallBudget:
    def __init__(self, max_attempts=6, max_wire_calls=6, *, deadline=None):
        if not 0 < max_attempts <= 6 or not 0 < max_wire_calls <= 6:
            raise ValueError("invalid call budget")
        self.max_attempts, self.max_wire_calls = max_attempts, max_wire_calls
        self.attempts = self.wire_calls = 0
        self.deadline = monotonic() + 60 if deadline is None else deadline

    def _reserve(self, name, maximum):
        if monotonic() >= self.deadline:
            raise RuntimeFailure("timeout")
        if getattr(self, name) >= maximum:
            raise RuntimeFailure("tool_budget_exhausted")
        setattr(self, name, getattr(self, name) + 1)

    def reserve_attempt(self, call_id=None):
        self._reserve("attempts", self.max_attempts)

    def reserve_wire_call(self, call_id=None):
        self._reserve("wire_calls", self.max_wire_calls)

    begin_attempt = reserve_attempt
    reserve_wire = reserve_wire_call


@dataclass(frozen=True)
class ExecutionHost:
    registry: object
    targets: object
    credentials: object
    audit: object
    authorize: object


class DynamicToolObservation(StrictModel):
    tool: str
    object_id: None = None
    queried_at: AwareDatetime
    outcome: Literal["ok", "unknown", "error"]
    reason: str | None
    facts: None = None
    source: None = None
    evidence: ReceivedEvidence | None
    complete: bool
    required_capability: Capability


class _ExecutorBoundCallAdapter:
    def __init__(self, snapshot, host, budget, entry, request, output_model):
        self.snapshot, self.host, self.budget = snapshot, host, budget
        self.entry, self.request, self.output_model = entry, request, output_model

    async def _check(self, lease, registration):
        await self.host.registry.assert_current(lease)
        await self._authority_check(lease, registration)

    async def _authority_check(self, lease, registration):
        if monotonic() >= self.budget.deadline:
            raise RuntimeFailure("timeout")
        host, snapshot = self.host, self.snapshot
        if await _maybe_await(host.authorize(snapshot)) is not True:
            raise RuntimeFailure("access_denied")
        if lease.target_policy_version != host.targets.policy_version:
            raise RuntimeFailure("stale_generation")
        if registration.connection.credential_ref is not None:
            _, generation = await _maybe_await(
                host.credentials.resolve(
                    registration.tenant_id, registration.connection.credential_ref
                )
            )
            if generation != lease.credential_generation:
                raise RuntimeFailure("stale_generation")

    async def __call__(self, identity, params):
        # Keep SDK task-group ownership and bounded cleanup in one shielded task.
        owner = asyncio.create_task(self._execute(identity, params))
        try:
            return await asyncio.shield(owner)
        except asyncio.CancelledError:
            if not owner.done():
                owner.cancel()
            while not owner.done():
                try:
                    await asyncio.shield(owner)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not owner.cancelled():
                owner.exception()
            raise

    async def _execute(self, identity, params):
        snapshot, host, entry = self.snapshot, self.host, self.entry
        request = CapabilityRequest.model_validate_json(json.dumps(params))
        if identity != snapshot.identity or request != self.request:
            raise ValueError("access_denied")
        if await _maybe_await(host.authorize(snapshot)) is not True:
            raise RuntimeFailure("access_denied")
        registration, lease = await host.registry.resolve_business(identity, entry)
        if lease != dict(snapshot.leases).get(entry.alias):
            raise RuntimeFailure("stale_generation")
        await self._check(lease, registration)
        manager = RuntimeManager(host.targets, host.credentials, host.registry)
        started, call_id = monotonic(), uuid4().hex

        wire_sent = False

        async def before_call():
            nonlocal wire_sent
            await self._check(lease, registration)
            self.budget.reserve_wire_call(call_id)
            wire_sent = True

        raw = ""
        try:
            async with asyncio.timeout(min(4.8, max(0, self.budget.deadline - monotonic()))):
                async with _business_session(manager, registration, lease, before_call) as (
                    session,
                    pending,
                ):
                    await manager._run_guarded(session.initialize(), lease, session, pending)
                    tools, cursor, seen, cursors = {}, None, set(), set()
                    for _ in range(10):
                        page = await manager._run_guarded(
                            session.list_tools(cursor=cursor), lease, session, pending
                        )
                        for tool in page.tools:
                            if tool.name in seen or len(seen) >= 50:
                                raise ValueError("stale_schema")
                            seen.add(tool.name)
                            tools[tool.name] = sanitize_tool(
                                tool.name, tool.inputSchema, tool.outputSchema
                            )
                        cursor = page.nextCursor
                        if cursor is None:
                            break
                        if cursor in cursors:
                            raise ValueError("stale_schema")
                        cursors.add(cursor)
                    else:
                        raise ValueError("stale_schema")
                    tool = tools.get(entry.original_name)
                    inp, out = expected_schemas(entry.capability)
                    if tool is None or (
                        tool.input_schema_json != canonical_schema(inp)
                        or tool.output_schema_json != canonical_schema(out)
                    ):
                        raise ValueError("stale_schema")
                    result = await manager._run_guarded(
                        session.call_tool(entry.original_name, request.model_dump(mode="json")),
                        lease,
                        session,
                        pending,
                    )
                    if result.isError or result.structuredContent is None:
                        raise ValueError("data_error")
                    raw = json.dumps(result.structuredContent, ensure_ascii=False, allow_nan=False)
                    if len(raw.encode("utf-8")) > 65536:
                        raise ValueError("oversized_result")
                    evidence = bind_evidence(DynamicEvidence.model_validate_json(raw), request)
                    if evidence.data_origin != registration.data_origin:
                        raise ValueError("data_error")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = (
                "timeout" if isinstance(exc, TimeoutError) else _exception_code(exc, "data_error")
            )
            if isinstance(exc, ValueError) and str(exc) in {"stale_schema", "oversized_result"}:
                code = str(exc)
            if wire_sent:
                await self._publish_result(
                    identity, lease, registration, call_id, raw, started, error_code=code
                )
            if code == "timeout":
                raise TimeoutError from None
            if code == "data_error":
                raise ValueError(code) from None
            raise RuntimeFailure(code) from None
        receipt = await self._publish_result(identity, lease, registration, call_id, raw, started)
        return self.output_model(
            tool=entry.alias,
            queried_at=snapshot.query_at,
            outcome=evidence.outcome,
            reason=evidence.reason,
            evidence=ReceivedEvidence(remote=evidence, host=receipt),
            complete=evidence.complete,
            required_capability=entry.capability,
        )

    async def _publish_result(
        self, identity, lease, registration, call_id, raw, started, error_code=None
    ):
        snapshot, host, entry = self.snapshot, self.host, self.entry
        # Close transport before authoritative publication checks and PG locking.
        await self._check(lease, registration)
        receipt = HostReceipt(
            service_id=entry.service_id,
            tool_name=entry.original_name,
            call_id=call_id,
            received_at=datetime.now(timezone.utc),
            config_version=registration.config_version,
            catalog_version=snapshot.catalog_id,
            route_version=snapshot.directory_version,
            response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            selection_reason="single_authorized_source",
        )
        await host.audit.publish(
            identity,
            lease,
            receipt,
            alias=entry.alias,
            capability=entry.capability,
            task_id=snapshot.task_id,
            run_id=snapshot.run_id,
            correlation_id=snapshot.correlation_id,
            elapsed_ms=int((monotonic() - started) * 1000),
            guard=lambda: self._authority_check(lease, registration),
            error_code=error_code,
            evidence_valid=error_code is None,
            request=self.request,
            response_hash_available=bool(raw),
        )
        return receipt


def build_dynamic_definitions(snapshot, host, budget):
    definitions, requests = [], dict(snapshot.requests)
    if len(requests) != len(snapshot.requests) or set(requests) != {
        e.alias for e in snapshot.entries
    }:
        raise ValueError("invalid task grants")
    for entry in snapshot.entries:
        request = CapabilityRequest.model_validate_json(requests[entry.alias])
        if (
            request.capability != entry.capability
            or request.queried_at != snapshot.query_at
            or request.factory_id not in entry.factory_ids
        ):
            raise ValueError("invalid task grants")
        output = create_model(
            "Dynamic_" + entry.alias,
            __base__=DynamicToolObservation,
            tool=(Literal[entry.alias], entry.alias),
            required_capability=(Literal[entry.capability], entry.capability),
        )
        handler = _ExecutorBoundCallAdapter(snapshot, host, budget, entry, request, output)
        definitions.append(
            ToolDefinition(
                entry.alias,
                "Query authorized " + entry.capability,
                CapabilityRequest,
                output,
                handler,
                lambda: snapshot.query_at,
            )
        )
    return ToolRegistry(definitions)


class InquiryAuditStore:
    """Independent 023 initializer and transactional publication against current head."""

    def __init__(self, registry):
        self.registry = registry

    async def initialize(self, admin):
        from pathlib import Path

        from psycopg import sql as sql_builder

        from anlan.tools.dynamic_mcp.registry import RegistryError

        self.registry.authorize(admin, None, "schema_initialize")
        sql = (Path(__file__).parents[2] / "sql" / "023_dynamic_mcp_calls.sql").read_text(
            encoding="utf-8-sig"
        )
        fingerprint = hashlib.sha256(sql.encode()).hexdigest()
        async with self.registry._connection() as conn:
            await self.registry._lock(conn, "migration:dynamic-mcp:23")
            row = await (
                await conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM anlan_v2.anlan_schema_migrations "
                    "WHERE version=23) AS present"
                )
            ).fetchone()
            if row["present"]:
                shape = await (
                    await conn.execute(
                        "SELECT obj_description('anlan_v2.dynamic_mcp_calls'::regclass) AS hash"
                    )
                ).fetchone()
                if shape["hash"] != fingerprint:
                    raise RegistryError("invalid_configuration")
                return
            await conn.execute(sql)
            await conn.execute(
                sql_builder.SQL("COMMENT ON TABLE anlan_v2.dynamic_mcp_calls IS {}").format(
                    sql_builder.Literal(fingerprint)
                )
            )

    async def publish(
        self,
        identity,
        lease,
        receipt,
        *,
        alias,
        capability,
        task_id,
        run_id,
        correlation_id,
        elapsed_ms,
        guard=None,
        error_code=None,
        evidence_valid=True,
        request=None,
        response_hash_available=True,
    ):
        from psycopg.types.json import Jsonb

        from anlan.tools.dynamic_mcp.catalog import ValidationReport
        from anlan.tools.dynamic_mcp.registry import RegistryError

        allowed_errors = {
            None,
            "data_error",
            "oversized_result",
            "stale_schema",
            "timeout",
            "disconnected",
            "tool_budget_exhausted",
            "access_denied",
            "stale_generation",
            "storage_unavailable",
            "credential_unavailable",
            "cleanup_failed",
        }
        if (
            error_code not in allowed_errors
            or type(evidence_valid) is not bool
            or evidence_valid != (error_code is None)
            or type(response_hash_available) is not bool
            or (evidence_valid and not response_hash_available)
        ):
            raise RegistryError("invalid_configuration")
        request_json = None
        if request is not None:
            request = CapabilityRequest.model_validate_json(request.model_dump_json())
            if request.capability != capability:
                raise RegistryError("invalid_configuration")
            request_json = request.model_dump(mode="json")
        receipt = HostReceipt.model_validate_json(receipt.model_dump_json())
        if receipt.service_id != lease.service_id:
            raise RegistryError("access_denied")
        async with self.registry._connection() as conn:
            # FOR SHARE conflicts with disable/refresh/replace's FOR UPDATE and update.
            row = await self.registry._business_current(conn, identity, lease)
            report = ValidationReport.model_validate(row["validation_json"])
            if not report.valid or not any(
                t.alias == alias
                and t.capability == capability
                and t.original_name == receipt.tool_name
                for t in report.tools
            ):
                raise RegistryError("access_denied")
            if guard is not None:
                await _maybe_await(guard())
            await conn.execute(
                "INSERT INTO anlan_v2.dynamic_mcp_calls "
                "(tenant_id,call_id,user_id,service_id,generation,config_revision,discovery_id,"
                "alias,capability,task_id,run_id,correlation_id,elapsed_ms,receipt_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    identity.tenant_id,
                    receipt.call_id,
                    identity.user_id,
                    lease.service_id,
                    lease.generation,
                    lease.config_revision,
                    lease.discovery_id,
                    alias,
                    capability,
                    task_id,
                    run_id,
                    correlation_id,
                    elapsed_ms,
                    Jsonb(
                        receipt.model_dump(mode="json")
                        | {
                            "error_code": error_code,
                            "evidence_valid": evidence_valid,
                            "request": request_json,
                            "response_hash_available": response_hash_available,
                        }
                    ),
                ),
            )
