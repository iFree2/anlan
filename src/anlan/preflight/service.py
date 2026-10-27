"""Authorized durable preflight orchestration and metadata-only completion validation."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from anlan.common.errors import AccessDenied, InvalidTransition, TaskBusy
from anlan.common.models import Identity
from anlan.infrastructure.collaboration import CollaborationStore
from anlan.infrastructure.preflight import PrecheckStore
from anlan.preflight.catalog import CatalogService
from anlan.preflight.contracts import EvidenceKey, RecheckCommand
from anlan.preflight.evaluator import evaluate, timestamp
from anlan.tools.queries import MAX_SOURCE_BYTES, read_bytes


def evidence_key(application, state, binding):
    return EvidenceKey(
        task_id=application.task_id,
        material_revision=state["revision"],
        binding_revision=binding.binding_revision,
        application_version=application.version,
    )


def source_signature(result):
    if not result:
        return None
    return {
        "worker": result.get("worker", {}).get("source"),
        "area": result.get("area", {}).get("source"),
        "knowledge": result.get("knowledge", {}).get("source", []),
        "acl_hash": result.get("acl_hash"),
        "knowledge_acl_hashes": result.get("knowledge_acl_hashes"),
    }


class PreflightService:
    def __init__(self, dsn, config, service_context_factory, runner=None, *, clock=None):
        self.store = PrecheckStore(dsn)
        self.applications = CollaborationStore(dsn)
        self.config, self.service_context_factory = config, service_context_factory
        self.runner = runner
        self.clock = clock or (lambda: config.as_of or datetime.now(UTC))

    async def _acl_hash(self):
        raw = await asyncio.wait_for(read_bytes(self.config.facts_dir / "access.json"), 2)
        if len(raw) > MAX_SOURCE_BYTES:
            raise AccessDenied("授权源不可用")
        return hashlib.sha256(raw).hexdigest()

    async def file_fingerprints(self):
        fingerprints = {}
        for filename in ("qualifications.json", "areas.json"):
            try:
                raw = await asyncio.wait_for(read_bytes(self.config.facts_dir / filename), 2)
                fingerprints[filename] = (
                    hashlib.sha256(raw).hexdigest() if len(raw) <= MAX_SOURCE_BYTES else "oversized"
                )
            except (OSError, TimeoutError):
                fingerprints[filename] = None
        return fingerprints

    async def require_binding(self, actor, task_id, expected, conn):
        binding = await self.store.get_binding(actor.tenant_id, task_id, conn=conn)
        if binding is None or expected != binding.binding_revision:
            raise InvalidTransition("人员、资质及区域未确认，或冻结的绑定版本已过期")
        await CatalogService(self.config).validate(actor, binding.references)
        return binding

    async def enqueue(
        self, conn, actor, application, state, binding, *, cause="automatic", request_id=None
    ):
        return await self.store.enqueue(
            actor,
            evidence_key(application, state, binding),
            {
                "actor": actor.model_dump(mode="json"),
                "references": binding.references.model_dump(mode="json"),
                "fields": state["fields"],
                "request_id": request_id,
            },
            conn=conn,
            cause=cause,
        )

    async def sources_current(self, actor, job, conn):
        """No embeddings, fact queries or model calls. Knowledge rows stay locked through commit."""
        result = job["result"]
        try:
            initiator = Identity(tenant_id=job["tenant_id"], user_id=job["actor_user_id"])
            if self.config.collaboration_role(initiator) not in {"applicant", "safety_manager"}:
                return False
            await self.applications.get(
                initiator, self.config.collaboration_role(initiator), job["task_id"], conn=conn
            )
            binding = await self.store.get_binding(actor.tenant_id, job["task_id"], conn=conn)
            if binding is None:
                return False
            await CatalogService(self.config).validate(actor, binding.references)
            await CatalogService(self.config).validate(initiator, binding.references)
            if await self._acl_hash() != result.get("acl_hash"):
                return False
            fingerprints = await self.file_fingerprints()
            if fingerprints != result.get("source_fingerprints"):
                return False
            for name, filename in (("worker", "qualifications.json"), ("area", "areas.json")):
                source = result.get(name, {}).get("source") or {}
                if source and fingerprints[filename] != source.get("sha256"):
                    return False
            citations = result.get("knowledge", {}).get("citations", [])
            now = self.clock()
            for citation in sorted(citations, key=lambda item: (item["doc_id"], item["chunk_id"])):
                row = await (
                    await conn.execute(
                        "SELECT d.*,c.content_hash AS chunk_hash "
                        "FROM anlan_v2.knowledge_documents d "
                        "JOIN anlan_v2.knowledge_chunks c USING(tenant_id,doc_id,version) "
                        "WHERE d.tenant_id=%s AND d.doc_id=%s AND d.version=%s AND c.chunk_id=%s "
                        "FOR SHARE OF d,c",
                        (
                            actor.tenant_id,
                            citation["doc_id"],
                            citation["version"],
                            citation["chunk_id"],
                        ),
                    )
                ).fetchone()
                if (
                    not row
                    or not row["current"]
                    or row["withdrawn"]
                    or actor.user_id not in row["allowed_users"]
                    or initiator.user_id not in row["allowed_users"]
                    or not row["valid_from"] <= now < row["valid_until"]
                    or row["content_hash"] != citation["document_hash"]
                    or row["chunk_hash"] != citation["content_hash"]
                    or row["source"] != citation["source"]
                    or row["valid_from"] != timestamp(citation["valid_from"])
                    or row["valid_until"] != timestamp(citation["valid_until"])
                    or hashlib.sha256(json.dumps(sorted(row["allowed_users"])).encode()).hexdigest()
                    != result.get("knowledge_acl_hashes", {}).get(citation["doc_id"])
                ):
                    return False
            return True
        except (AccessDenied, OSError, ValueError, KeyError, TimeoutError):
            return False

    async def current(self, conn, actor, application, state, binding, job):
        if binding is None or job is None or job["result"] is None:
            return False
        latest = await self.store.latest(actor.tenant_id, application.task_id, conn=conn)
        if latest is None or latest["job_id"] != job["job_id"]:
            return False
        version = application.version - (application.status == "review_completed")
        if (
            job["material_revision"] != state["revision"]
            or job["binding_revision"] != binding.binding_revision
            or job["application_version"] != version
            or job["result"].get("stale")
            or job["input_snapshot"]["fields"] != state["fields"]
            or job["input_snapshot"]["references"] != binding.references.model_dump()
        ):
            return False
        result = job["result"]
        limit = timestamp(result.get("valid_until"))
        return bool(limit and self.clock() < limit and await self.sources_current(actor, job, conn))

    async def complete(self, conn, actor, application, state, command):
        binding = await self.require_binding(
            actor, application.task_id, command.expected_binding_revision, conn
        )
        job = await self.store.latest(actor.tenant_id, application.task_id, conn=conn)
        selected = command.applied_knowledge_citation_ids
        if (
            not job
            or not command.expected_check_id
            or command.expected_check_id != job["check_id"]
            or not selected
            or len(selected) != len(set(selected))
            or not await self.current(conn, actor, application, state, binding, job)
        ):
            raise InvalidTransition("本轮预核查已过时、不完整，或尚未明确选择实际适用的引用")
        result = job["result"]
        assessment = evaluate(result["worker"], result["area"], result["knowledge"], self.clock())
        if not assessment.ready or not set(selected) <= set(assessment.citation_ids):
            raise InvalidTransition("依据存在缺口/异常或引用不属于本轮有效结果")

    async def recheck(self, actor, task_id, payload):
        command = RecheckCommand.model_validate(payload)
        async with self.service_context_factory() as workflow:
            async with workflow._registry.locked(actor, task_id, action="read") as record:
                conn = workflow._registry.conn
                async with conn.transaction():
                    app = await self.applications.get(
                        actor,
                        self.config.collaboration_role(actor),
                        task_id,
                        conn=conn,
                        for_update=True,
                    )
                    role = self.config.collaboration_role(actor)
                    if (
                        role == "applicant" and app.status not in {"draft", "changes_requested"}
                    ) or (role == "safety_manager" and app.status == "review_completed"):
                        raise InvalidTransition("当前阶段不允许该身份重查")
                    workflow._config(record)
                    workflow._check_mode(record)
                    snapshot = await workflow._snapshot(record)
                    state = snapshot.values
                    if (
                        not state
                        or await workflow._registry.pending(task_id)
                        or snapshot.next
                        or snapshot.interrupts
                    ):
                        raise InvalidTransition("材料尚需补充或恢复")
                    binding = await self.require_binding(
                        actor, task_id, command.expected_binding_revision, conn
                    )
                    namespace = json.dumps(
                        ["precheck-recheck-v1", actor.tenant_id, actor.user_id, command.request_id]
                    )
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s,20))", (namespace,)
                    )
                    old = await (
                        await conn.execute(
                            "SELECT * FROM anlan_v2.precheck_recheck_commands "
                            "WHERE tenant_id=%s AND actor_user_id=%s AND request_id=%s",
                            (actor.tenant_id, actor.user_id, command.request_id),
                        )
                    ).fetchone()
                    if old:
                        if old["task_id"] != task_id or old["payload"] != command.model_dump():
                            raise InvalidTransition("重查 request_id 的任务或完整载荷冲突")
                        return {"job_id": old["job_id"]}
                    if (
                        state["revision"] != command.expected_material_revision
                        or app.version != command.expected_application_version
                    ):
                        raise InvalidTransition("重查冻结的材料或申请版本已过期")
                    job = await self.enqueue(
                        conn,
                        actor,
                        app,
                        state,
                        binding,
                        cause="recheck:" + hashlib.sha256(namespace.encode()).hexdigest(),
                        request_id=command.request_id,
                    )
                    await conn.execute(
                        "INSERT INTO anlan_v2.precheck_recheck_commands "
                        "(tenant_id,actor_user_id,request_id,task_id,payload,job_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (
                            actor.tenant_id,
                            actor.user_id,
                            command.request_id,
                            task_id,
                            Jsonb(command.model_dump()),
                            job["job_id"],
                        ),
                    )
                    return {"job_id": job["job_id"]}

    async def process_next(self, job_id=None):
        attempt = await self.store.claim(job_id)
        if attempt is None:
            return None
        job = attempt["job"]
        actor = Identity(tenant_id=job["tenant_id"], user_id=job["actor_user_id"])
        result = {
            "ready": False,
            "stale": True,
            "issues": ["access_or_input_changed"],
            "citation_ids": [],
            "rules_version": "preflight-v1",
        }
        try:
            async with self.service_context_factory() as workflow:
                async with workflow._registry.locked(
                    actor, job["task_id"], action="read"
                ) as record:
                    app = await self.applications.get(
                        actor,
                        self.config.collaboration_role(actor),
                        job["task_id"],
                        conn=workflow._registry.conn,
                    )
                    binding = await self.store.get_binding(
                        actor.tenant_id, job["task_id"], conn=workflow._registry.conn
                    )
                    workflow._check_mode(record)
                    snapshot = await workflow._snapshot(record)
                    state = snapshot.values
                    if (
                        not binding
                        or not state
                        or await workflow._registry.pending(job["task_id"])
                        or snapshot.next
                        or snapshot.interrupts
                        or state["status"] != "awaiting_review"
                        or evidence_key(app, state, binding).model_dump()
                        != {
                            key: job[key]
                            for key in (
                                "task_id",
                                "material_revision",
                                "binding_revision",
                                "application_version",
                            )
                        }
                    ):
                        raise InvalidTransition("预核查输入已改变")
                    await CatalogService(self.config).validate(actor, binding.references)
                    acl = await self._acl_hash()
            # No transaction or task lock survives across this read-only I/O.
            result = await self.runner.run(
                actor, job["input_snapshot"]["references"], job["input_snapshot"]["fields"]
            )
            result["acl_hash"] = acl
            result["source_fingerprints"] = await self.file_fingerprints()
        except (AccessDenied, InvalidTransition):
            pass
        except TaskBusy:
            await self.store.defer(job["job_id"], attempt["attempt_id"])
            return None
        except Exception:
            result = {
                "ready": False,
                "issues": ["source_unavailable"],
                "citation_ids": [],
                "rules_version": "preflight-v1",
            }
        # Internal result publication uses the same PG advisory task key, never actor substitution.
        async with self.service_context_factory() as workflow:
            conn = workflow._registry.conn
            async with conn.transaction():
                locked = await (
                    await conn.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS ok",
                        (job["task_id"],),
                    )
                ).fetchone()
                if not locked["ok"]:
                    await self.store.defer(job["job_id"], attempt["attempt_id"], conn=conn)
                    return None
                try:
                    async with workflow._registry.locked(
                        actor, job["task_id"], action="read"
                    ) as rec:
                        app = await self.applications.get(
                            actor, self.config.collaboration_role(actor), job["task_id"], conn=conn
                        )
                        binding = await self.store.get_binding(
                            actor.tenant_id, job["task_id"], conn=conn
                        )
                        workflow._check_mode(rec)
                        snapshot = await workflow._snapshot(rec)
                        state = snapshot.values
                        if (
                            await workflow._registry.pending(job["task_id"])
                            or snapshot.next
                            or snapshot.interrupts
                        ):
                            result["stale"] = True
                        check_job = job | {"result": result}
                        result["knowledge_acl_hashes"] = {}
                        for citation in result.get("knowledge", {}).get("citations", []):
                            metadata = await (
                                await conn.execute(
                                    "SELECT allowed_users FROM anlan_v2.knowledge_documents "
                                    "WHERE tenant_id=%s AND doc_id=%s AND version=%s FOR SHARE",
                                    (actor.tenant_id, citation["doc_id"], citation["version"]),
                                )
                            ).fetchone()
                            if metadata:
                                result["knowledge_acl_hashes"][citation["doc_id"]] = hashlib.sha256(
                                    json.dumps(sorted(metadata["allowed_users"])).encode()
                                ).hexdigest()
                        if not await self.current(conn, actor, app, state, binding, check_job):
                            result["stale"] = True
                except (AccessDenied, InvalidTransition):
                    result["stale"] = True
                return await self.store.finish(
                    job["job_id"], attempt["attempt_id"], result, conn=conn
                )

    async def serve(self):
        while True:
            try:
                if await self.process_next() is not None:
                    continue
            except Exception:
                # Leases/attempts provide restart recovery; no paid retry is performed.
                pass
            await asyncio.sleep(0.25)
