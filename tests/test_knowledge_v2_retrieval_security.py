"""Current-authority boundaries, including per-provider input isolation."""

import asyncio
import json

import pytest
from test_knowledge_v2_retrieval import api, harness, selector, synthetic_doc


class RankSpy:
    version = "deterministic-fixture/1"

    def __init__(self, hook=None):
        self.seen = []
        self.hook = hook

    async def rank(self, question, candidates, limit):
        self.seen.append(candidates)
        if self.hook:
            self.hook()
        return tuple(api().RankedKey(key=c.key, score=1.0) for c in candidates[:limit])


def revoke(ledger, doc, kind="withdraw"):
    record = ledger.records[(doc.tenant_id, doc.logical_document_id)]
    if kind == "acl":
        record[0] = record[0].model_copy(update={"allowed_users": (), "revision": 2})
    elif kind == "version":
        record[1] = record[1].model_copy(
            update={"withdrawn_versions": (doc.document_version_id,), "revision": 2}
        )
    elif kind == "release":
        record[2] = record[2].model_copy(update={"generation": doc.generation + 1})
    else:
        record[1] = record[1].model_copy(update={"withdrawn": True, "revision": 2})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["withdraw", "acl", "version", "release"])
async def test_per_provider_rebuild_removes_revoked_text_before_vector(kind):
    a, b = synthetic_doc("a", text="SECRET_A"), synthetic_doc("b", text="PUBLIC_B")
    lexical, vector = RankSpy(), RankSpy()
    service, request, ledger, *_ = harness((a, b), lexical=lexical, vector=vector)
    lexical.hook = lambda: revoke(ledger, a, kind)
    packet = await service.search(request, api().SearchParams(question="q", mode="hybrid"))
    assert vector.seen and all(c.key.logical_document_id == "b" for c in vector.seen[0])
    assert "SECRET_A" not in str(vector.seen)
    assert all(i.key.logical_document_id == "b" for i in packet.items)
    code = "release_changed" if kind == "release" else "authorization_changed"
    assert code in {i.code for i in packet.issues}


@pytest.mark.asyncio
async def test_all_revoked_before_vector_means_zero_calls():
    doc, lexical, vector = synthetic_doc(), RankSpy(), RankSpy()
    service, request, ledger, *_ = harness((doc,), lexical=lexical, vector=vector)
    lexical.hook = lambda: revoke(ledger, doc)
    packet = await service.search(request, api().SearchParams(question="q", mode="hybrid"))
    assert vector.seen == [] and packet.items == () and packet.status == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tenant", "acl", "withdraw", "scope", "unpublished", "missing"])
async def test_prefilter_denials_never_reach_rank_provider(kind):
    doc = synthetic_doc(tenant="foreign" if kind == "tenant" else "tenant-a")
    lexical = RankSpy()
    service, request, ledger, *_ = harness((doc,), lexical=lexical)
    record = ledger.records[(doc.tenant_id, doc.logical_document_id)]
    if kind in {"acl", "withdraw"}:
        revoke(ledger, doc, kind)
    elif kind == "scope":
        request = request.model_copy(update={"scope": ()})
    elif kind == "unpublished":
        record[2] = None
    elif kind == "missing":
        record[1] = None
    packet = await service.search(request, api().SearchParams(question="SYNTHETIC"))
    assert lexical.seen == [] and packet.items == () and packet.status == "unknown"
    if kind == "tenant":
        assert ledger.calls == 0 and "foreign" not in packet.model_dump_json()


@pytest.mark.asyncio
async def test_projection_await_revoke_removes_previously_accumulated_child():
    doc = synthetic_doc(text="SYNTHETIC parent\nchild")
    data = json.loads(doc.model_dump_json())
    data["blocks"][1]["parent_id"] = doc.blocks[0].block_id
    doc = type(doc).model_validate_json(json.dumps(data))
    service, request, ledger, resolver, _ = harness((doc,))
    original = resolver.resolve

    async def resolve(key):
        result = await original(key)
        if key.block_id == doc.blocks[0].block_id:
            revoke(ledger, doc)
        return result

    resolver.resolve = resolve
    selected = selector(doc).model_copy(update={"block_id": doc.blocks[1].block_id})
    packet = await service.get_clause(request, api().ClauseParams(selector=selected))
    assert packet.items == () and packet.status == "unknown"


@pytest.mark.asyncio
async def test_missing_parent_projection_is_explicit_incomplete():
    doc = synthetic_doc(text="SYNTHETIC parent\nchild")
    data = json.loads(doc.model_dump_json())
    data["blocks"][1]["parent_id"] = doc.blocks[0].block_id
    doc = type(doc).model_validate_json(json.dumps(data))
    service, request, _, resolver, _ = harness((doc,))
    resolver.projection.pop(api().key_for(doc, doc.blocks[0].block_id))
    selected = selector(doc).model_copy(update={"block_id": doc.blocks[1].block_id})
    packet = await service.get_clause(request, api().ClauseParams(selector=selected))
    assert packet.status == "incomplete" and len(packet.items) == 1
    assert packet.items[0].dependency_state == "incomplete"


@pytest.mark.asyncio
async def test_source_ir_tampering_and_projection_tampering_are_blocked():
    doc = synthetic_doc()
    service, request, ledger, resolver, _ = harness((doc,))
    key = api().key_for(doc, doc.blocks[0].block_id)
    resolver.projection[key] = doc.blocks[0].model_copy(update={"source_text": "FAKE"})
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert not packet.items and packet.status == "error"
    assert "data_error" in {i.code for i in packet.issues}
    ledger.records[(doc.tenant_id, doc.logical_document_id)][2] = ledger.records[
        (doc.tenant_id, doc.logical_document_id)
    ][2].model_copy(update={"ir_sha256": "f" * 64})
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert not packet.items


@pytest.mark.asyncio
async def test_large_evidence_is_not_truncated_into_fake_complete_quote():
    doc = synthetic_doc(text="SYNTHETIC " + "中" * 24000)
    service, request, *_ = harness((doc,))
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert len(packet.model_dump_json().encode()) <= 65536
    assert not packet.items and "byte_limited" in {i.code for i in packet.issues}


@pytest.mark.asyncio
async def test_deadline_and_cancellation_are_observable():
    lexical = RankSpy()
    service, request, _, _, clock = harness(lexical=lexical)
    lexical.hook = lambda: setattr(clock, "elapsed", 6.0)
    packet = await service.search(request, api().SearchParams(question="q"))
    assert not packet.items and "deadline_exceeded" in {i.code for i in packet.issues}
    entered = asyncio.Event()

    class CancelProvider:
        version = "cancel-fixture/1"

        async def rank(self, question, candidates, limit):
            entered.set()
            await asyncio.Event().wait()

    service, request, *_ = harness(lexical=CancelProvider())
    task = asyncio.create_task(service.search(request, api().SearchParams(question="q")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_final_recheck_revoke_and_old_manifest_rollback_never_resurrect():
    doc = synthetic_doc()
    service, request, ledger, *_ = harness((doc,))
    ledger.hook = lambda source, *_: revoke(source, doc) if source.calls == 3 else None
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert packet.items == () and packet.status == "unknown"
    ledger.hook = None  # Same old IR/release with latest revoked authority.
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert packet.items == ()


@pytest.mark.asyncio
async def test_authority_budget_cannot_bypass_final_check(monkeypatch):
    service, request, *_ = harness()
    monkeypatch.setattr(api("service"), "MAX_AUTH_READS", 2)
    doc = service.catalog.documents[0]
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert not packet.items
    assert "authority_budget_exhausted" in {i.code for i in packet.issues}


@pytest.mark.asyncio
async def test_thirty_third_dependency_keeps_incomplete():
    doc = synthetic_doc(text="\n".join(f"SYNTHETIC {i}" for i in range(33)))
    data = json.loads(doc.model_dump_json())
    for n in range(1, 33):
        data["blocks"][n]["parent_id"] = doc.blocks[n - 1].block_id
    doc = type(doc).model_validate_json(json.dumps(data))
    service, request, *_ = harness((doc,))
    selected = selector(doc).model_copy(update={"block_id": doc.blocks[-1].block_id})
    packet = await service.get_clause(request, api().ClauseParams(selector=selected))
    assert len(packet.items) <= 32 and packet.status == "incomplete"
    assert all(item.dependency_state == "incomplete" for item in packet.items)
    assert "node_limited" in {i.code for i in packet.issues}


@pytest.mark.asyncio
async def test_concurrent_tenants_and_candidate_corpus_bound():
    a, b = synthetic_doc("a"), synthetic_doc("b", tenant="tenant-b")
    service, request, *_ = harness((a, b))
    other = request.model_copy(update={"tenant_id": "tenant-b", "request_id": "other"})
    packets = await asyncio.gather(
        service.get_clause(request, api().ClauseParams(selector=selector(a))),
        service.get_clause(other, api().ClauseParams(selector=selector(b))),
    )
    assert packets[0].items[0].key.tenant_id == "tenant-a"
    assert packets[1].items[0].key.tenant_id == "tenant-b"
    lexical = RankSpy()
    doc = synthetic_doc(text="\n".join(f"SYNTHETIC {n}" for n in range(257)))
    service, request, *_ = harness((doc,), lexical=lexical)
    packet = await service.search(request, api().SearchParams(question="q"))
    assert len(lexical.seen[0]) == 256
    assert "candidate_truncated" in {i.code for i in packet.issues}


@pytest.mark.asyncio
async def test_real_async_timeout_cancels_provider_and_discards_late_evidence(monkeypatch):
    cancelled = asyncio.Event()

    class WaitingProvider:
        version = "waiting-fixture/1"

        async def rank(self, question, candidates, limit):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    service, request, *_ = harness(lexical=WaitingProvider())
    monkeypatch.setattr(api("service"), "MAX_SECONDS", 0.05)
    packet = await service.search(request, api().SearchParams(question="q"))
    assert cancelled.is_set() and not packet.items
    assert "deadline_exceeded" in {i.code for i in packet.issues}


@pytest.mark.asyncio
async def test_dependency_byte_trimming_marks_child_incomplete():
    doc = synthetic_doc(text="SYNTHETIC " + "中" * 24000 + "\nsmall child")
    data = json.loads(doc.model_dump_json())
    data["blocks"][1]["parent_id"] = doc.blocks[0].block_id
    doc = type(doc).model_validate_json(json.dumps(data))
    service, request, *_ = harness((doc,))
    selected = selector(doc).model_copy(update={"block_id": doc.blocks[1].block_id})
    packet = await service.get_clause(request, api().ClauseParams(selector=selected))
    assert packet.status == "incomplete" and len(packet.items) == 1
    assert packet.items[0].source_text == "small child"
    assert packet.items[0].dependency_state == "incomplete"
    assert len(packet.model_dump_json().encode()) <= 65536


@pytest.mark.asyncio
async def test_release_restoration_cannot_reintroduce_document_in_same_request():
    a, b = synthetic_doc("a"), synthetic_doc("b")
    lexical, vector = RankSpy(), RankSpy()
    service, request, ledger, *_ = harness((a, b), lexical=lexical, vector=vector)
    old = ledger.records[(a.tenant_id, a.logical_document_id)][2]
    lexical.hook = lambda: revoke(ledger, a, "release")
    vector.hook = lambda: ledger.records[(a.tenant_id, a.logical_document_id)].__setitem__(2, old)
    packet = await service.search(request, api().SearchParams(question="q", mode="hybrid"))
    assert all(i.key.logical_document_id != "a" for i in packet.items)
    assert all(c.key.logical_document_id != "a" for c in vector.seen[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["packet", "serialize"])
async def test_final_assembly_and_serialization_deadline_discards_evidence(monkeypatch, phase):
    doc = synthetic_doc()
    service, request, _, _, clock = harness((doc,))
    if phase == "packet":
        original = clock.utc_now
        calls = 0

        def now():
            nonlocal calls
            calls += 1
            if calls == 5:  # All three governance checks passed before packet construction.
                clock.elapsed = 6.0
            return original()

        clock.utc_now = now
    else:
        original = api().EvidencePacket.model_dump_json

        def slow_serialize(packet, *args, **kwargs):
            result = original(packet, *args, **kwargs)
            clock.elapsed = 6.0
            return result

        monkeypatch.setattr(api().EvidencePacket, "model_dump_json", slow_serialize)
    packet = await service.get_clause(request, api().ClauseParams(selector=selector(doc)))
    assert not packet.items and not packet.table_rows
    assert "deadline_exceeded" in {issue.code for issue in packet.issues}
    assert len(packet.model_dump_json().encode()) <= 65536
    assert all(event.key_digest is None for event in packet.audit)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["withdraw", "acl", "release"])
async def test_revoked_parent_issue_cannot_leak_formerly_visible_node_id(kind):
    doc = synthetic_doc(text="SYNTHETIC parent\nchild")
    data = json.loads(doc.model_dump_json())
    data["blocks"][1]["parent_id"] = doc.blocks[0].block_id
    doc = type(doc).model_validate_json(json.dumps(data))
    service, request, ledger, resolver, _ = harness((doc,))
    resolver.projection.pop(api().key_for(doc, doc.blocks[0].block_id))
    ledger.hook = lambda source, *_: revoke(source, doc, kind) if source.calls == 5 else None
    selected = selector(doc).model_copy(update={"block_id": doc.blocks[1].block_id})
    packet = await service.get_clause(request, api().ClauseParams(selector=selected))
    assert not packet.items
    assert all(issue.related_key is None for issue in packet.issues)
    assert doc.blocks[0].block_id not in packet.model_dump_json()
    assert all(event.key_digest is None for event in packet.audit)


@pytest.mark.asyncio
async def test_issue_only_document_also_gets_final_authority_recheck():
    a, b = synthetic_doc("a", text="SECRET A"), synthetic_doc("b", text="PUBLIC B")
    lexical = RankSpy()
    service, request, ledger, resolver, _ = harness((a, b), lexical=lexical)
    resolver.projection.pop(api().key_for(a, a.blocks[0].block_id))
    original = resolver.resolve

    async def resolving(key):
        result = await original(key)
        if key.logical_document_id == "b":
            revoke(ledger, a)
        return result

    resolver.resolve = resolving
    packet = await service.search(request, api().SearchParams(question="q"))
    assert any(item.key.logical_document_id == "b" for item in packet.items)
    assert all(
        issue.related_key is None or issue.related_key.logical_document_id != "a"
        for issue in packet.issues
    )
