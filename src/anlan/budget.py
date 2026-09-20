"""Durable shared model-call reservations; every reserved attempt consumes its limit."""

import re
from functools import wraps
from importlib.resources import files
from uuid import UUID, uuid4

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from anlan.postgres import _conninfo

AUTHORIZATION_ID = "20260920-long-term-v1"
_ERROR_CATEGORIES = frozenset({
    "http_error", "transport_error", "timeout", "invalid_response", "cancelled", "unknown_error",
    "model_timeout", "model_unavailable", "model_rate_limited", "model_unauthorized",
    "invalid_output",
})
_USAGE_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})


class BudgetError(RuntimeError):
    """Safe, credential-free budget failure."""


class BudgetExceeded(BudgetError):
    """The total or package reservation limit was reached."""


class BudgetConflict(BudgetError):
    """An authorization or immutable completion does not match."""


class BudgetUnavailable(BudgetError):
    """The persistent ledger cannot be reached or updated."""


def _hide_database_errors(method):
    @wraps(method)
    async def safe(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except psycopg.Error:
            pass
        # Raise outside the handler so even __context__ cannot disclose the DSN.
        raise BudgetUnavailable("模型调用预算账本不可用；连接详情已隐藏")
    return safe


class BudgetLedger:
    """Each operation opens its own connection and commits before returning.

    Custom authorization IDs are for trusted callers such as isolated integration
    tests. The production CLI always uses AUTHORIZATION_ID. There is no refund,
    reset, deletion, or reusable reservation API.
    """

    def __init__(self, dsn: str, authorization_id: str = AUTHORIZATION_ID,
                 total_limit: int = 100, package_limit: int = 10):
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            raise ValueError("authorization_id must be non-empty")
        for name, value, maximum in (("total_limit", total_limit, 100),
                                     ("package_limit", package_limit, 10)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} is outside the authorized bounds")
        self._dsn = dsn
        self.authorization_id = authorization_id
        self.total_limit = total_limit
        self.package_limit = package_limit

    async def _connect(self):
        return await AsyncConnection.connect(_conninfo(self._dsn), row_factory=dict_row)

    async def _authorization(self, conn):
        cursor = await conn.execute(
            "SELECT total_limit, package_limit FROM anlan_v2.model_budget_authorizations "
            "WHERE authorization_id=%s FOR UPDATE", (self.authorization_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise BudgetConflict("模型调用预算授权尚未初始化")
        if row["total_limit"] != self.total_limit or row["package_limit"] != self.package_limit:
            raise BudgetConflict("已有模型调用预算授权的上限不可变更")
        return row

    @_hide_database_errors
    async def initialize(self) -> None:
        async with await self._connect() as conn:
            # Transaction-scoped DDL lock also serializes concurrent initializers.
            await conn.execute("SELECT pg_advisory_xact_lock(73421103)")
            await conn.execute("CREATE SCHEMA IF NOT EXISTS anlan_v2")
            migration = files("anlan").joinpath("sql/002_model_budget.sql").read_text(
                encoding="utf-8")
            await conn.execute(migration, prepare=False)
            await conn.execute(
                "INSERT INTO anlan_v2.model_budget_authorizations "
                "(authorization_id, total_limit, package_limit) VALUES (%s,%s,%s) "
                "ON CONFLICT (authorization_id) DO NOTHING",
                (self.authorization_id, self.total_limit, self.package_limit),
            )
            await self._authorization(conn)

    @_hide_database_errors
    async def reserve(self, work_package: str, run_id: str) -> str:
        if not isinstance(work_package, str) or not re.fullmatch(
                r"P[1-7]-WP[0-9]{2}", work_package, flags=re.IGNORECASE | re.ASCII):
            raise ValueError("work_package must use P[1-7]-WP00 format")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be non-empty")
        work_package = work_package.upper()
        attempt_id = str(uuid4())
        async with await self._connect() as conn:
            limits = await self._authorization(conn)
            # All writers hold the authorization row lock through the insertion
            # and commit. Counts include failed and unresolved reservations.
            cursor = await conn.execute(
                "SELECT count(*) AS total, count(*) FILTER (WHERE work_package=%s) AS package "
                "FROM anlan_v2.model_budget_attempts WHERE authorization_id=%s",
                (work_package, self.authorization_id),
            )
            counts = await cursor.fetchone()
            if counts["total"] >= limits["total_limit"]:
                raise BudgetExceeded("模型调用累计预占额度已用尽")
            if counts["package"] >= limits["package_limit"]:
                raise BudgetExceeded("当前工作包模型调用预占额度已用尽")
            await conn.execute(
                "INSERT INTO anlan_v2.model_budget_attempts "
                "(attempt_id, authorization_id, work_package, run_id) VALUES (%s,%s,%s,%s)",
                (attempt_id, self.authorization_id, work_package, run_id),
            )
        return attempt_id

    @_hide_database_errors
    async def finish(self, attempt_id: str, status: str, usage: dict | None = None,
                     error: str | None = None) -> None:
        if status not in ("succeeded", "failed"):
            raise ValueError("status must be succeeded or failed")
        if error is not None and (not isinstance(error, str) or error not in _ERROR_CATEGORIES):
            raise ValueError("error must be a sanitized error category")
        if usage is not None:
            if not isinstance(usage, dict) or set(usage) - _USAGE_KEYS:
                raise ValueError("usage contains unsupported fields")
            if any(value is not None and (type(value) is not int or value < 0)
                   for value in usage.values()):
                raise ValueError("usage must contain non-negative integer or null values")
            usage = dict(usage)
        try:
            attempt_id = str(UUID(attempt_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("attempt_id must be a UUID") from None
        async with await self._connect() as conn:
            cursor = await conn.execute(
                "SELECT status, usage, error FROM anlan_v2.model_budget_attempts "
                "WHERE attempt_id=%s AND authorization_id=%s FOR UPDATE",
                (attempt_id, self.authorization_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise BudgetConflict("模型调用预占记录不存在")
            if row["status"] != "reserved":
                if (row["status"], row["usage"], row["error"]) == (status, usage, error):
                    return
                raise BudgetConflict("模型调用完成记录不可覆盖")
            await conn.execute(
                "UPDATE anlan_v2.model_budget_attempts SET status=%s, usage=%s, error=%s, "
                "finished_at=clock_timestamp() WHERE attempt_id=%s AND authorization_id=%s",
                (status, Jsonb(usage) if usage is not None else None, error,
                 attempt_id, self.authorization_id),
            )

    @_hide_database_errors
    async def snapshot(self) -> dict:
        async with await self._connect() as conn:
            limits = await self._authorization(conn)
            cursor = await conn.execute(
                "SELECT attempt_id, work_package, run_id, status, usage, error, "
                "reserved_at, finished_at FROM anlan_v2.model_budget_attempts "
                "WHERE authorization_id=%s ORDER BY reserved_at, attempt_id",
                (self.authorization_id,),
            )
            attempts = await cursor.fetchall()
        packages = {}
        statuses = {"reserved": 0, "succeeded": 0, "failed": 0}
        for attempt in attempts:
            attempt["attempt_id"] = str(attempt["attempt_id"])
            for key in ("reserved_at", "finished_at"):
                if attempt[key] is not None:
                    attempt[key] = attempt[key].isoformat()
            package = attempt["work_package"]
            packages[package] = packages.get(package, 0) + 1
            statuses[attempt["status"]] += 1
        return {"authorization_id": self.authorization_id, **limits,
                "total_reserved": len(attempts), "packages": packages,
                "status_counts": statuses, "attempts": attempts}
