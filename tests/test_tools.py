"""真实合成JSON查询；权限、时间和故障不由模型猜测。"""

import asyncio
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from anlan.contracts import Identity

NOW = datetime.fromisoformat("2026-09-20T12:00:00+00:00")
OWNER = Identity(tenant_id="synthetic-demo", user_id="safety-manager-demo")


@pytest.fixture
def dataset(tmp_path):
    source = Path("examples/synthetic/facts-v1")
    assert source.is_dir(), "versioned synthetic facts are not implemented"
    shutil.copytree(source, tmp_path / "facts")
    return tmp_path / "facts"


def make_tools(dataset, **kwargs):
    from anlan.tools.queries import FactTools
    return FactTools(dataset, clock=lambda: NOW, **kwargs)


async def test_real_record_query_and_source_digest(dataset):
    tools = make_tools(dataset)
    result = await tools.query_worker_qualification(
        OWNER, {"worker_id": "worker-001", "qualification_type": "welding"})
    assert result.outcome == "ok"
    assert result.facts == {"qualification_type": "welding", "status": "active"}
    assert result.source.version == "qualifications-v1"
    assert result.source.sha256 == hashlib.sha256(
        (dataset / "qualifications.json").read_bytes()).hexdigest()
    assert result.queried_at == NOW
    assert result.source.valid_until > NOW
    document = json.loads((dataset / "qualifications.json").read_text(encoding="utf-8"))
    document["records"][0]["status"] = "suspended"
    (dataset / "qualifications.json").write_text(json.dumps(document), encoding="utf-8")
    changed = await tools.query_worker_qualification(
        OWNER, {"worker_id": "worker-001", "qualification_type": "welding"})
    assert changed.facts["status"] == "suspended"
    assert changed.source.sha256 != result.source.sha256


@pytest.mark.parametrize("worker,kind,reason", [
    ("worker-missing", "welding", "missing"),
    ("worker-expired", "welding", "expired"),
    ("worker-future", "welding", "not_yet_valid"),
    ("worker-001", "electrical", "not_applicable"),
])
async def test_unknown_reasons_are_not_negative_qualification(dataset, worker, kind, reason):
    result = await make_tools(dataset).query_worker_qualification(
        OWNER, {"worker_id": worker, "qualification_type": kind})
    assert (result.outcome, result.reason, result.facts) == ("unknown", reason, None)
    assert result.source.version == "qualifications-v1"


@pytest.mark.parametrize("area,reason", [
    ("area-001", None), ("area-expired", "expired"), ("area-missing", "missing"),
])
async def test_area_reads_current_or_unknown(dataset, area, reason):
    result = await make_tools(dataset).query_area_status(OWNER, {"area_id": area})
    assert result.reason == reason
    assert result.outcome == ("ok" if reason is None else "unknown")
    assert result.facts == ({"status": "restricted"} if reason is None else None)


@pytest.mark.parametrize("identity,worker", [
    (Identity(tenant_id="other", user_id=OWNER.user_id), "worker-001"),
    (Identity(tenant_id=OWNER.tenant_id, user_id="other"), "worker-001"),
    (OWNER, "other-tenant-worker"),
])
async def test_denial_does_not_read_facts_or_reveal_foreign_source(dataset, identity, worker):
    reads = []

    async def reader(path):
        reads.append(path.name)
        return path.read_bytes()

    result = await make_tools(dataset, reader=reader).query_worker_qualification(
        identity, {"worker_id": worker, "qualification_type": "welding"})
    assert (result.outcome, result.reason) == ("error", "access_denied")
    assert reads == ["access.json"]
    assert result.source is None and result.facts is None


@pytest.mark.parametrize("payload", [
    {"worker_id": "worker-001", "qualification_type": "welding", "tenant_id": "other"},
    {"worker_id": 1, "qualification_type": "welding"},
    {"worker_id": "../access", "qualification_type": "welding"},
    {"worker_id": "", "qualification_type": "welding"},
])
async def test_invalid_parameters_never_reach_reader(dataset, payload):
    async def must_not_read(path):
        pytest.fail("invalid parameters reached data reader")

    result = await make_tools(dataset, reader=must_not_read).query_worker_qualification(
        OWNER, payload)
    assert (result.outcome, result.reason) == ("error", "invalid_parameters")


async def test_timeout_cancels_reader_and_returns_no_fact(dataset):
    cancelled = asyncio.Event()

    async def slow(path):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    result = await make_tools(dataset, reader=slow, timeout_seconds=0.01).query_area_status(
        OWNER, {"area_id": "area-001"})
    assert cancelled.is_set()
    assert (result.outcome, result.reason, result.facts) == ("error", "timeout", None)


@pytest.mark.parametrize("corruption", ["missing", "invalid_json", "bad_time", "duplicate"])
async def test_bad_source_is_error_and_does_not_leak_exception(dataset, corruption):
    path = dataset / "areas.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "missing":
        path.unlink()
    elif corruption == "invalid_json":
        path.write_text("SECRET malformed content", encoding="utf-8")
    else:
        if corruption == "bad_time":
            doc["records"][0]["valid_until"] = "2026-01-01T00:00:00Z"
        else:
            doc["records"].append(doc["records"][0])
        path.write_text(json.dumps(doc), encoding="utf-8")
    result = await make_tools(dataset).query_area_status(OWNER, {"area_id": "area-001"})
    assert (result.outcome, result.reason) == ("error", "data_error")
    assert "SECRET" not in result.model_dump_json()
    assert result.facts is None


async def test_valid_until_is_exclusive_and_future_observation_is_unknown(dataset):
    path = dataset / "areas.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["records"][0]["valid_until"] = NOW.isoformat()
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = await make_tools(dataset).query_area_status(OWNER, {"area_id": "area-001"})
    assert result.reason == "expired"
    doc["records"][0]["valid_until"] = "2026-09-21T00:00:00Z"
    doc["records"][0]["observed_at"] = "2026-09-20T13:00:00Z"
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = await make_tools(dataset).query_area_status(OWNER, {"area_id": "area-001"})
    assert result.reason == "not_yet_valid"


async def test_non_yielding_work_cannot_publish_success_after_deadline(dataset):
    import time

    async def blocking_reader(path):
        if path.name == "areas.json":
            time.sleep(0.03)  # 模拟同步解析/本地读取占用事件循环。
        return path.read_bytes()

    result = await make_tools(dataset, reader=blocking_reader,
                              timeout_seconds=0.001).query_area_status(
                                  OWNER, {"area_id": "area-001"})
    assert (result.outcome, result.reason, result.facts) == ("error", "timeout", None)


async def test_oversized_document_is_rejected_before_parsing(dataset):
    path = dataset / "areas.json"
    path.write_bytes(path.read_bytes() + b" " * 262144)
    result = await make_tools(dataset).query_area_status(OWNER, {"area_id": "area-001"})
    assert (result.outcome, result.reason, result.facts) == ("error", "data_error", None)
