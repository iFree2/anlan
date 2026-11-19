"""Minimal actor/message-scoped query receipts; no raw questions or evidence."""

from importlib.resources import files
from typing import Literal

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, TypeAdapter, model_validator

from anlan.business_query.contracts import QueryType
from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import NonEmpty, StrictModel
from anlan.infrastructure.db import conninfo


class QueryReceipt(StrictModel):
    source_message_id: NonEmpty
    task_id: NonEmpty | None = None
    query_type: QueryType
    material_revision: int | None = Field(default=None, strict=True, ge=1)
    application_version: int | None = Field(default=None, strict=True, ge=1)
    evidence_schema_version: Literal["business-evidence-v1"] = "business-evidence-v1"
    citation_ids: list[NonEmpty] = Field(default_factory=list, max_length=3)
    outcome: Literal["ok", "unknown", "selection_required", "error"]

    @model_validator(mode="after")
    def versions_move_together(self):
        values = (self.task_id, self.material_revision, self.application_version)
        if any(v is None for v in values) and any(v is not None for v in values):
            raise ValueError("task and versions move together")
        return self


class BusinessQueryAuditStore:
    def __init__(self, dsn):
        self.dsn = dsn

    async def connect(self):
        return await AsyncConnection.connect(conninfo(self.dsn), row_factory=dict_row)

    async def initialize(self):
        async with await self.connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421121)")
            await conn.execute(files("anlan").joinpath("sql/021_business_queries.sql").read_text(
                encoding="utf-8"), prepare=False)

    async def record(self, actor, role, receipt):
        role = TypeAdapter(Literal["applicant", "safety_manager"] | None).validate_python(role)
        receipt = QueryReceipt.model_validate(receipt)
        payload = receipt.model_dump(mode="json")
        async with await self.connect() as conn:
            await conn.execute(
                "INSERT INTO anlan_v2.business_query_receipts "
                "(tenant_id,actor_user_id,actor_role,source_message_id,task_id,query_type,"
                "material_revision,application_version,evidence_schema_version,"
                "citation_ids,outcome) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (actor.tenant_id, actor.user_id, role, receipt.source_message_id, receipt.task_id,
                 receipt.query_type, receipt.material_revision, receipt.application_version,
                 receipt.evidence_schema_version, Jsonb(receipt.citation_ids), receipt.outcome))
            row = await self._get(conn, actor, receipt.source_message_id)
            if row["actor_role"] != role or any(row[k] != v for k, v in payload.items()):
                raise InvalidTransition("相同消息的查询回执不可覆盖")
            return row

    async def get(self, actor, source_message_id):
        source_message_id = TypeAdapter(NonEmpty).validate_python(source_message_id)
        async with await self.connect() as conn:
            return await self._get(conn, actor, source_message_id)

    @staticmethod
    async def _get(conn, actor, source_message_id):
        row = await (await conn.execute(
            "SELECT * FROM anlan_v2.business_query_receipts "
            "WHERE tenant_id=%s AND actor_user_id=%s AND source_message_id=%s",
            (actor.tenant_id, actor.user_id, source_message_id))).fetchone()
        if row is None:
            raise AccessDenied("查询回执不存在或当前身份无权访问")
        return row
