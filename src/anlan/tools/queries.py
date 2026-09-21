"""两个固定只读查询：先授权，后读取版本化合成事实；无模型或重试。"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from anlan.common.models import Identity
from anlan.tools.contracts import (
    AccessData,
    Area,
    AreaQuery,
    FactData,
    Qualification,
    Source,
    ToolResult,
    WorkerQuery,
)

MESSAGES = {
    None: "已读取合成事实，仍需人工复核；不是作业批准。",
    "missing": "授权范围内未找到记录，当前事实未知。",
    "expired": "记录已过有效期，不能作为当前事实。",
    "not_yet_valid": "记录尚未生效或观察时间晚于查询时点。",
    "not_applicable": "现有记录不适用于所查询资质类型。",
    "invalid_parameters": "参数无效；仅接受业务对象ID和所需资质类型。",
    "access_denied": "无权查询该对象，不提供其存在性或事实信息。",
    "timeout": "查询超时，当前事实未知；不是资质不合格。",
    "data_error": "合成来源无法读取或不符合数据合同，当前事实未知。",
}
MAX_SOURCE_BYTES = 262144


async def read_bytes(path: Path) -> bytes:
    # 本地文件I/O在线程中运行；超时不等待线程，迟到结果不会发布或写回。
    def bounded_read():
        with path.open("rb") as source:
            return source.read(MAX_SOURCE_BYTES + 1)
    return await asyncio.to_thread(bounded_read)


class FactTools:
    def __init__(self, directory: Path, *, clock: Callable[[], datetime] | None = None,
                 reader: Callable[[Path], Awaitable[bytes]] = read_bytes,
                 timeout_seconds: float = 2.0):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout must be within (0, 30]")
        self.directory = directory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.reader = reader
        self.timeout_seconds = timeout_seconds

    async def query_worker_qualification(self, identity: Identity, parameters: dict) -> ToolResult:
        return await self._query(identity, parameters, worker=True)

    async def query_area_status(self, identity: Identity, parameters: dict) -> ToolResult:
        return await self._query(identity, parameters, worker=False)

    async def _query(self, identity: Identity, parameters: dict, *, worker: bool) -> ToolResult:
        started = perf_counter()
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware time")
        tool = "query_worker_qualification" if worker else "query_area_status"
        object_id = None

        def result(outcome, reason=None, source=None, facts=None):
            return ToolResult(
                tool=tool, object_id=object_id, queried_at=now, outcome=outcome,
                reason=reason, message=MESSAGES[reason], source=source, facts=facts,
                elapsed_ms=round((perf_counter() - started) * 1000, 2))

        try:
            query = (WorkerQuery if worker else AreaQuery).model_validate(parameters)
        except ValidationError:
            return result("error", "invalid_parameters")
        object_id = query.worker_id if worker else query.area_id

        async def lookup():
            async def load(filename, schema):
                raw = await self.reader(self.directory / filename)
                if len(raw) > MAX_SOURCE_BYTES:
                    raise ValueError("source too large")
                data = await asyncio.to_thread(schema.model_validate_json, raw)
                return raw, data

            _, access = await load("access.json", AccessData)
            allowed = any(
                grant.tenant_id == identity.tenant_id and grant.user_id == identity.user_id
                and object_id in (grant.worker_ids if worker else grant.area_ids)
                for grant in access.records)
            if not allowed:
                return result("error", "access_denied")
            filename = "qualifications.json" if worker else "areas.json"
            raw, data = await load(filename, FactData)
            expected = Qualification if worker else Area
            if any(not isinstance(record, expected) for record in data.records):
                return result("error", "data_error")
            source = Source(resource=filename, version=data.version,
                            sha256=hashlib.sha256(raw).hexdigest())
            records = [r for r in data.records
                       if r.tenant_id == identity.tenant_id and r.object_id == object_id]
            if not records:
                return result("unknown", "missing", source)
            if worker:
                records = [r for r in records if r.qualification_type == query.qualification_type]
                if not records:
                    return result("unknown", "not_applicable", source)
            record = records[0]
            source = source.model_copy(update={key: getattr(record, key) for key in (
                "record_id", "observed_at", "valid_from", "valid_until")})
            if now < record.valid_from or now < record.observed_at:
                return result("unknown", "not_yet_valid", source)
            if now >= record.valid_until:
                return result("unknown", "expired", source)
            facts = {"status": record.status}
            if worker:
                facts["qualification_type"] = record.qualification_type
            return result("ok", source=source, facts=facts)

        try:
            found = await asyncio.wait_for(lookup(), timeout=self.timeout_seconds)
            # wait_for无法抢占同步工作；发布前再次检查单调时钟，丢弃迟到结果。
            if perf_counter() - started >= self.timeout_seconds:
                return result("error", "timeout")
            return found
        except TimeoutError:
            return result("error", "timeout")
        except (OSError, ValueError):
            return result("error", "data_error")
