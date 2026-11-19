"""Per-request governed evidence assembly, with no legacy integration or I/O."""

import asyncio
import hashlib
import json

from anlan.knowledge.governance.policy import AccessContext, evaluate_access
from anlan.knowledge.retrieval.contracts import (
    AuditEvent,
    CandidateText,
    EvidenceIssue,
    EvidenceItem,
    EvidenceKey,
    EvidencePacket,
    GovernanceRead,
    key_for,
)

MAX_SECONDS = 5.0
MAX_NODES = 32
MAX_PACKET_BYTES = 65536
MAX_AUTH_READS = 128
MAX_RESOLVES = 32


def _doc_id(doc):
    return (doc.tenant_id, doc.logical_document_id, doc.document_version_id, doc.generation)


def _fingerprint(model):
    canonical = json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class _Stop(Exception):
    pass


class KnowledgeRetrievalService:
    def __init__(self, catalog, governance, resolver, vector, clock, *, lexical=None):
        from anlan.knowledge.retrieval.ranking import LocalBM25

        self.catalog, self.governance, self.resolver = catalog, governance, resolver
        self.vector, self.clock = vector, clock
        self.lexical = LocalBM25() if lexical is None else lexical
        for provider in (self.lexical, self.vector):
            if provider is not None and (
                type(provider.version) is not str
                or not provider.version.strip()
                or len(provider.version) > 120
            ):
                raise ValueError("invalid_provider_version")

    async def search(self, request, params):
        return await _Run(self, request, "search").execute(params)

    async def get_clause(self, request, params):
        return await _Run(self, request, "get_clause").execute(params)

    async def query_table(self, request, params):
        return await _Run(self, request, "query_table").execute(params)


class _Run:
    def __init__(self, service, request, operation):
        self.s, self.req, self.operation = service, request, operation
        self.started = self.s.clock.utc_now()
        self.deadline = self.s.clock.monotonic() + MAX_SECONDS
        self.items, self.fingerprints, self.invalid = {}, {}, set()
        self.rows, self.issues, self.audit, self.versions = [], [], [], []
        self.reads = self.resolves = 0
        self.audit_truncated = False

    def issue(self, code, key=None):
        if key is not None and len(key.model_dump_json().encode()) > 512:
            key = None
        issue = EvidenceIssue(code=code, related_key=key)
        if issue not in self.issues:
            self.issues.append(issue)

    def record(self, stage, code, key=None):
        if len(self.audit) >= 128:
            self.audit_truncated = True
            return
        self.audit.append(
            AuditEvent(
                stage=stage, decision_code=code, key_digest=_fingerprint(key) if key else None
            )
        )

    def time_check(self):
        if self.s.clock.monotonic() >= self.deadline:
            self.issue("deadline_exceeded")
            raise _Stop()

    async def call(self, factory):
        self.time_check()
        try:
            result = await asyncio.wait_for(factory(), self.deadline - self.s.clock.monotonic())
        except TimeoutError:
            self.issue("deadline_exceeded")
            raise _Stop() from None
        self.time_check()
        return result

    def discard(self, doc):
        ident = _doc_id(doc)
        self.invalid.add(ident)
        self.items = {k: v for k, v in self.items.items() if k.sort_key[:4] != ident}
        self.rows = [r for r in self.rows if r.table_key.sort_key[:4] != ident]
        sanitized = []
        for issue in self.issues:
            if issue.related_key is not None and issue.related_key.sort_key[:4] == ident:
                issue = EvidenceIssue(code=issue.code)
            if issue not in sanitized:
                sanitized.append(issue)
        self.issues = sanitized
        removed_digests = {_fingerprint(key_for(doc, b.block_id)) for b in doc.blocks}
        self.audit = [
            event.model_copy(update={"key_digest": None})
            if event.key_digest in removed_digests
            else event
            for event in self.audit
        ]

    async def check(self, doc, *, final=False):
        ident = _doc_id(doc)
        if ident in self.invalid or doc.tenant_id != self.req.tenant_id:
            return None
        if self.reads >= MAX_AUTH_READS or (
            not final and self.reads + 1 + len(self.fingerprints) > MAX_AUTH_READS
        ):
            self.issue("authority_budget_exhausted")
            raise _Stop()
        checked_at = self.s.clock.utc_now()
        self.reads += 1
        try:
            read = await self.call(
                lambda: self.s.governance.read_current(
                    tenant_id=doc.tenant_id,
                    logical_document_id=doc.logical_document_id,
                    checked_at=checked_at,
                )
            )
            if not isinstance(read, GovernanceRead):
                raise ValueError("invalid_governance_read")
        except _Stop:
            raise
        except Exception:
            self.issue("data_error")
            self.discard(doc)
            return None
        previous = self.fingerprints.get(ident)
        fingerprint = _fingerprint(read.manifest) if read.manifest else None
        if previous is not None and fingerprint != previous:
            self.issue("release_changed")
            self.discard(doc)
            return None
        context = AccessContext(
            tenant_id=self.req.tenant_id,
            user_id=self.req.user_id,
            checked_at=checked_at,
            effective_at=self.req.effective_at,
            scope=self.req.scope,
        )
        decision = evaluate_access(doc, context, read.authority, read.manifest)
        self.record("governance", decision.reason)
        if not decision.allowed:
            if previous is not None:
                self.issue("authorization_changed")
                self.discard(doc)
            return None
        self.fingerprints[ident] = fingerprint
        return read

    async def visible(self):
        result, size = [], 0
        for doc in self.s.catalog.documents:
            if doc.tenant_id != self.req.tenant_id or await self.check(doc) is None:
                continue
            for block in sorted(doc.blocks, key=lambda b: b.block_id):
                self.time_check()
                amount = len(block.retrieval_text.encode())
                if len(result) >= 256 or size + amount > 1024 * 1024:
                    self.issue("candidate_truncated")
                    return tuple(result)
                result.append(
                    CandidateText(
                        key=key_for(doc, block.block_id), retrieval_text=block.retrieval_text
                    )
                )
                size += amount
        return tuple(result)

    async def route(self, provider, question):
        from anlan.knowledge.retrieval.ranking import validate_ranked

        candidates = await self.visible()  # Fresh read and rebuilt text for EACH provider.
        if not candidates:
            return ()
        self.versions.append(provider.version)
        try:
            result = await self.call(lambda: provider.rank(question, candidates, 20))
            ranked = validate_ranked(result, candidates, 20)
        except _Stop:
            raise
        except Exception:
            self.issue("provider_contract_error")
            return ()
        docs = {}
        for candidate in candidates:
            pair = self.s.catalog.lookup(candidate.key)
            docs[_doc_id(pair[0])] = pair[0]
        for doc in docs.values():
            await self.check(doc)
        return tuple(r for r in ranked if r.key.sort_key[:4] not in self.invalid)

    async def expand(self, keys):
        pending, visited = list(keys), set()
        while pending:
            self.time_check()
            key = pending.pop(0)
            if key in visited:
                continue
            if len(visited) >= MAX_NODES:
                self.issue("node_limited")
                break
            visited.add(key)
            pair = self.s.catalog.lookup(key)
            if pair is None:
                self.issue("not_found")
                continue
            doc, expected = pair
            if await self.check(doc) is None:
                continue
            if self.resolves >= MAX_RESOLVES:
                self.issue("node_limited")
                break
            self.resolves += 1
            try:
                block = await self.call(lambda: self.s.resolver.resolve(key))
            except _Stop:
                raise
            except Exception:
                self.issue("data_error")
                continue
            read = await self.check(doc)
            if read is None:
                continue
            if block is None:
                self.issue("projection_missing", key)
                continue
            if block != expected:
                self.issue("data_error", key)
                continue
            refs = tuple(
                dict.fromkeys(
                    (*((block.parent_id,) if block.parent_id else ()), *block.dependencies)
                )
            )
            required = tuple(key_for(doc, ref) for ref in refs)
            self.items[key] = EvidenceItem(
                key=key,
                title=doc.title,
                source_uri=doc.source_uri,
                source_text=block.source_text,
                locator=block.locator,
                source_sha256=doc.source_sha256,
                ir_sha256=doc.content_digest(),
                generation=doc.generation,
                lineage=doc.lineage,
                checked_at=read.authority.checked_at,
                release_fingerprint=self.fingerprints[_doc_id(doc)],
                acl_revision=read.authority.acl.revision,
                withdrawal_revision=read.authority.withdrawal.revision,
                dependency_state="complete",
                required_keys=required,
                table=block.table,
            )
            self.record("projection", "matched", key)
            pending.extend(required)

    def repair(self):
        incomplete = {
            k for k, item in self.items.items() if not set(item.required_keys) <= self.items.keys()
        }
        while True:
            extra = {k for k, item in self.items.items() if set(item.required_keys) & incomplete}
            if extra <= incomplete:
                break
            incomplete |= extra
        for key, item in tuple(self.items.items()):
            state = "incomplete" if key in incomplete else "complete"
            self.items[key] = item.model_copy(update={"dependency_state": state})
        if incomplete:
            self.issue("dependency_incomplete")
        tables = {k for k, item in self.items.items() if item.table is not None}
        self.rows = [r for r in self.rows if r.table_key in tables]

    def packet(self):
        self.repair()
        if self.items:
            status = "incomplete" if self.issues else "evidence_found"
        else:
            status = (
                "error"
                if any(i.code in {"data_error", "provider_contract_error"} for i in self.issues)
                else "unknown"
            )
        coverage = {
            "search": "limited_candidates",
            "get_clause": "exact_selection",
            "query_table": "table_range",
        }[self.operation]
        return EvidencePacket(
            operation=self.operation,
            request_id=self.req.request_id,
            requested_at=self.started,
            effective_at=self.req.effective_at,
            finished_at=self.s.clock.utc_now(),
            catalog_revision=self.s.catalog.revision,
            status=status,
            coverage=coverage,
            provider_versions=tuple(dict.fromkeys(self.versions)),
            items=tuple(
                sorted(
                    self.items.values(),
                    key=lambda i: (i.key.sort_key[:4], self.s.catalog.lookup(i.key)[1].order),
                )
            ),
            table_rows=tuple(self.rows),
            issues=tuple(self.issues),
            audit=tuple(self.audit),
            audit_truncated=self.audit_truncated,
            authority_reads=self.reads,
            projection_reads=self.resolves,
            elapsed_ms=max(0.0, (self.s.clock.monotonic() - (self.deadline - MAX_SECONDS)) * 1000),
        )

    async def finish(self):
        outgoing_keys = {
            *self.items,
            *(i.related_key for i in self.issues if i.related_key is not None),
        }
        docs = {
            _doc_id(self.s.catalog.lookup(k)[0]): self.s.catalog.lookup(k)[0] for k in outgoing_keys
        }
        for doc in docs.values():
            try:
                read = await self.check(doc, final=True)
            except _Stop:
                read = None
            if read is None:
                self.discard(doc)
            else:
                for key, item in tuple(self.items.items()):
                    if key.sort_key[:4] == _doc_id(doc):
                        self.items[key] = item.model_copy(
                            update={
                                "checked_at": read.authority.checked_at,
                                "acl_revision": read.authority.acl.revision,
                                "withdrawal_revision": read.authority.withdrawal.revision,
                            }
                        )
        if not self.items and not self.issues:
            self.issue("no_authorized_evidence")
        packet = self.bounded_packet()
        # Final guard includes assembly, UTF-8 serialization and all byte trimming.
        # No authority/provider/resolver task may start after this boundary.
        if self.s.clock.monotonic() >= self.deadline:
            self.items.clear()
            self.rows.clear()
            self.audit = [event.model_copy(update={"key_digest": None}) for event in self.audit]
            self.issues = list(dict.fromkeys(EvidenceIssue(code=i.code) for i in self.issues))
            self.issue("deadline_exceeded")
            packet = self.bounded_packet()
        return packet

    def bounded_packet(self):
        packet = self.packet()
        while len(packet.model_dump_json().encode()) > MAX_PACKET_BYTES:
            if self.audit:
                self.audit.pop()
                self.audit_truncated = True
            elif self.items:
                self.items.pop(next(reversed(self.items)))
                self.issue("byte_limited")
            else:
                raise ValueError("minimal_packet_exceeds_budget")
            packet = self.packet()
        return packet

    async def execute(self, params):
        try:
            if not self.req.scope:
                self.issue("applicability_unknown")
            elif self.operation == "search" and params.exact is None:
                from anlan.knowledge.retrieval.ranking import rrf

                routes = [await self.route(self.s.lexical, params.question)]
                if params.mode == "hybrid":
                    if self.s.vector is None:
                        self.issue("provider_unavailable")
                    else:
                        routes.append(await self.route(self.s.vector, params.question))
                routes = tuple(
                    tuple(r for r in route if r.key.sort_key[:4] not in self.invalid)
                    for route in routes
                )
                ranked = rrf(routes)
                await self.expand(tuple(r.key for r in ranked[: params.top_k]))
            else:
                selected = params.exact if self.operation == "search" else params.selector
                key = EvidenceKey(tenant_id=self.req.tenant_id, **selected.model_dump())
                await self.expand((key,))
                if self.operation == "query_table" and key in self.items:
                    from anlan.knowledge.retrieval.tables import query_table_block

                    self.time_check()
                    result = query_table_block(
                        self.s.catalog.lookup(key)[1], key, params.filters, params.row_limit
                    )
                    self.time_check()
                    self.rows.extend(result.rows)
                    for issue in result.issues:
                        self.issue(issue.code, issue.related_key)
                    if any(
                        i.code in {"physical_cell_location_unavailable", "data_error"}
                        for i in result.issues
                    ):
                        self.items.clear()
                        self.rows.clear()
        except _Stop:
            pass
        return await self.finish()
