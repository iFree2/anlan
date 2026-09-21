"""版本化合成示例知识：身份与时效过滤先于检索，回答仅摘录证据。"""

import hashlib
import json
import re
from datetime import UTC, datetime
from importlib.resources import files

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from anlan.common.errors import AccessDenied, InvalidTransition
from anlan.common.models import Identity
from anlan.infrastructure.db import conninfo
from anlan.knowledge.contracts import KnowledgeDocument, KnowledgeQuery
from anlan.knowledge.embeddings import validate_vectors


def chunks_for(document: KnowledgeDocument) -> list[dict]:
    chunks = []
    for paragraph in document.paragraphs:
        for start in range(0, len(paragraph), 360):
            text = paragraph[start:start + 360]
            ordinal = len(chunks)
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            ident = f"{document.doc_id}:{document.version}:{ordinal}:{content_hash}"
            chunks.append({"chunk_id": hashlib.sha256(ident.encode()).hexdigest()[:24],
                           "ordinal": ordinal, "text": text, "content_hash": content_hash})
    return chunks


def terms(text: str) -> set[str]:
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    return {token for part in parts for token in
            ([part] if part.isascii() or len(part) == 1 else
             [part[i:i + 2] for i in range(len(part) - 1)])}


class KnowledgeStore:
    def __init__(self, dsn: str, embeddings, *, clock=None):
        self.dsn = dsn
        self.embeddings = embeddings
        self.clock = clock or (lambda: datetime.now(UTC))

    async def _connect(self):
        return await AsyncConnection.connect(conninfo(self.dsn), row_factory=dict_row)

    async def initialize(self):
        async with await self._connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(73421104)")
            await conn.execute("CREATE SCHEMA IF NOT EXISTS anlan_v2")
            await conn.execute(files("anlan").joinpath("sql/003_knowledge.sql").read_text(
                encoding="utf-8"), prepare=False)

    async def ingest(self, identity: Identity, raw: dict) -> dict:
        document = KnowledgeDocument.model_validate(raw)
        chunks = chunks_for(document)
        digest = hashlib.sha256(document.model_dump_json().encode()).hexdigest()
        vectors = validate_vectors(await self.embeddings.embed([c["text"] for c in chunks]),
                                   len(chunks))
        async with await self._connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                               (json.dumps([identity.tenant_id, document.doc_id]),))
            old = await (await conn.execute(
                "SELECT * FROM anlan_v2.knowledge_documents WHERE tenant_id=%s "
                "AND doc_id=%s AND current FOR UPDATE",
                (identity.tenant_id, document.doc_id))).fetchone()
            if old:
                if old["owner_id"] != identity.user_id:
                    raise AccessDenied("不能修改其他用户拥有的示例文档")
                if old["withdrawn"]:
                    raise InvalidTransition("文档已撤回，不允许通过重复摄取自动恢复")
                if document.version <= old["version"]:
                    if (document.version == old["version"] and old["content_hash"] == digest
                            and old["embedding_model"] == self.embeddings.model_id):
                        return {"doc_id": document.doc_id, "version": document.version,
                                "chunks": len(chunks), "idempotent": True}
                    raise InvalidTransition("旧版本或同版本内容/编码器冲突")
                await conn.execute(
                    "UPDATE anlan_v2.knowledge_documents SET current=false "
                    "WHERE tenant_id=%s AND doc_id=%s AND current",
                    (identity.tenant_id, document.doc_id))
            await conn.execute(
                "INSERT INTO anlan_v2.knowledge_documents "
                "(tenant_id,doc_id,version,owner_id,title,source,content_hash,valid_from,valid_until,"
                "allowed_users,embedding_model) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (identity.tenant_id, document.doc_id, document.version, identity.user_id,
                 document.title, document.source, digest, document.valid_from, document.valid_until,
                 sorted(set(document.allowed_users + [identity.user_id])),
                 self.embeddings.model_id))
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO anlan_v2.knowledge_chunks "
                    "(tenant_id,doc_id,version,chunk_id,ordinal,body,content_hash,embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::public.vector)",
                    [(identity.tenant_id, document.doc_id, document.version, c["chunk_id"],
                      c["ordinal"], c["text"], c["content_hash"], json.dumps(vector))
                     for c, vector in zip(chunks, vectors, strict=True)])
        return {"doc_id": document.doc_id, "version": document.version,
                "chunks": len(chunks), "idempotent": False}

    async def withdraw(self, identity: Identity, doc_id: str):
        async with await self._connect() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                               (json.dumps([identity.tenant_id, doc_id]),))
            cursor = await conn.execute(
                "UPDATE anlan_v2.knowledge_documents SET withdrawn=true "
                "WHERE tenant_id=%s AND doc_id=%s AND owner_id=%s AND current RETURNING doc_id",
                (identity.tenant_id, doc_id, identity.user_id))
            if await cursor.fetchone() is None:
                raise AccessDenied("文档不存在或无权撤回")
        return {"doc_id": doc_id, "withdrawn": True}

    async def search(self, identity: Identity, parameters: dict) -> dict:
        query = KnowledgeQuery.model_validate(parameters)
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("knowledge clock must be timezone-aware")
        vector = validate_vectors(await self.embeddings.embed([query.question]), 1)[0]
        async with await self._connect() as conn:
            cursor = await conn.execute(
                "SELECT d.doc_id,d.version,d.title,d.source,d.valid_from,d.valid_until,"
                "d.content_hash AS document_hash,c.chunk_id,c.body,c.content_hash,"
                "1-(c.embedding OPERATOR(public.<=>) %s::public.vector) AS similarity "
                "FROM anlan_v2.knowledge_chunks c JOIN anlan_v2.knowledge_documents d "
                "USING(tenant_id,doc_id,version) WHERE d.tenant_id=%s AND %s=ANY(d.allowed_users) "
                "AND d.current AND NOT d.withdrawn AND d.valid_from<=%s AND d.valid_until>%s "
                "AND d.embedding_model=%s ORDER BY similarity DESC,d.doc_id,c.ordinal LIMIT 20",
                (json.dumps(vector), identity.tenant_id, identity.user_id, now, now,
                 self.embeddings.model_id))
            candidates = await cursor.fetchall()
        selected = [row for row in candidates if row["similarity"] >= query.minimum_score]
        question_terms = terms(query.question)
        for row in selected:
            overlap = len(question_terms & terms(row["body"])) / max(1, len(question_terms))
            row["rank_score"] = row["similarity"] if query.strategy == "vector" else \
                0.75 * row["similarity"] + 0.25 * overlap
        selected.sort(key=lambda row: (-row["rank_score"], row["doc_id"], row["chunk_id"]))
        citations = [{**{k: row[k] for k in (
            "doc_id", "version", "title", "source", "document_hash", "chunk_id", "content_hash")},
            "valid_from": row["valid_from"].isoformat(),
            "valid_until": row["valid_until"].isoformat(), "quote": row["body"],
            "similarity": round(row["similarity"], 6), "rank_score": round(row["rank_score"], 6),
        } for row in selected[:query.top_k]]
        return {
            "data_origin": "SYNTHETIC", "mode": "local_extract", "strategy": query.strategy,
            "outcome": "ok" if citations else "unknown", "queried_at": now.isoformat(),
            "reason": None if citations else "no_eligible_evidence",
            "message": "已找到候选示例片段，需人工复核。" if citations else
                "授权、时效与相似度范围内无可用依据；不等于没有制度要求。",
            "embedding_model": self.embeddings.model_id, "citations": citations,
            "answer_policy": "top1-extractive-v2",
            "answer": [{"claim": c["quote"], "chunk_id": c["chunk_id"]} for c in citations[:1]],
            "answer_notice": "仅摘录首条候选；其余供人工复核，不保证覆盖复合问题。",
            "notice": "仅示例知识原文摘录，不是实际制度或作业批准；文内指令不提供权限。",
        }
