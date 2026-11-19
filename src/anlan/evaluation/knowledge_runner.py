"""Native K2/K1/K3 execution with local-only instrumentation and isolated authority."""

import asyncio
import json
import platform
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, perf_counter
from uuid import uuid4

from anlan.knowledge.documents.contracts import DocumentIR
from anlan.knowledge.governance.policy import (
    ACLRecord,
    AuthoritySnapshot,
    ReleaseManifest,
    WithdrawalRecord,
)
from anlan.knowledge.parsing.contracts import SourceCandidate, TxtIngestMetadata
from anlan.knowledge.parsing.text import parse_txt
from anlan.knowledge.retrieval.catalog import InMemoryCatalog
from anlan.knowledge.retrieval.contracts import (
    CellFilter,
    ClauseParams,
    ClauseSelector,
    GovernanceRead,
    SearchParams,
    TableParams,
    TrustedRetrievalRequest,
    key_for,
)
from anlan.knowledge.retrieval.providers import DeterministicRankProvider, InMemoryBlockResolver
from anlan.knowledge.retrieval.ranking import LocalBM25
from anlan.knowledge.retrieval.service import KnowledgeRetrievalService

from .contracts import Manifest
from .knowledge_contracts import (
    FIXTURES,
    ROOT,
    Catalog,
    Observation,
    RunIndex,
    canonical,
    digest,
    fixture_path,
)
from .report import evaluate_bundle, write_report

NOW = datetime(2026, 11, 17, tzinfo=UTC)


def load_catalog(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(FIXTURES.resolve()):
        raise ValueError("catalog outside trusted root")
    return Catalog.model_validate_json(resolved.read_bytes())


def parse_source(raw, name, logical):
    metadata = TxtIngestMetadata(
        tenant_id="tenant-eval",
        logical_document_id=logical,
        document_version_id=logical + "-v1",
        generation=1,
        title="SYNTHETIC " + logical,
    )
    candidate = SourceCandidate(
        schema_version="knowledge.source-candidate.v1",
        candidate_id=logical,
        data_origin="SYNTHETIC",
        source_url="synthetic://evaluation/" + name,
        review_state="candidate",
        expected_source_sha256=digest(raw),
    )
    return parse_txt(raw, filename=name, metadata=metadata, candidate=candidate)


def release_inputs(doc):
    key = dict(tenant_id=doc.tenant_id, logical_document_id=doc.logical_document_id)
    return [
        ACLRecord(
            **key, revision=1, updated_at=NOW, allowed_users=("reader",), scope=("synthetic-plant",)
        ),
        WithdrawalRecord(**key, revision=1, updated_at=NOW, withdrawn=False, withdrawn_versions=()),
        ReleaseManifest(
            **key,
            document_version_id=doc.document_version_id,
            generation=doc.generation,
            source_sha256=doc.source_sha256,
            ir_sha256=doc.content_digest(),
            review_status="approved",
            reviewer="SYNTHETIC-evaluation-fixture",
            published_at=NOW - timedelta(days=1),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=1),
            scope=("synthetic-plant",),
        ),
    ]


class Clock:
    def utc_now(self):
        return NOW

    def monotonic(self):
        return monotonic()


async def execute_knowledge_case(case_id, root, eval_run_id, manifest_sha):
    directory = root / "cases" / case_id
    directory.mkdir(parents=True, exist_ok=False)
    case_run_id = str(uuid4())
    events = []
    active_request = None

    def event(kind, **data):
        events.append(
            dict(
                producer="evaluation_knowledge_runner",
                request_id=active_request,
                seq=len(events),
                eval_run_id=eval_run_id,
                case_run_id=case_run_id,
                case_id=case_id,
                kind=kind,
                data=data,
            )
        )

    started = perf_counter()
    sources = []
    drafts = []
    docs = []
    calls = []
    errors = []
    event("case_started", case_id=case_id)
    files = (
        {"normal.txt": "normal"}
        if case_id == "k3e-normal"
        else {"revoked-a.txt": "a", "allowed-b.txt": "b"}
        if case_id == "k3e-withdrawal"
        else {}
    )
    for name, logical in files.items():
        raw = fixture_path(name).read_bytes()
        sources.append(dict(name=name, logical=logical, hex=raw.hex(), sha256=digest(raw)))
        (directory / name).write_bytes(raw)
        event("parse_started", name=name, sha256=digest(raw))
        draft = parse_source(raw, name, logical)
        drafts.append(draft.model_dump(mode="json", exclude={"raw_bytes"}))
        docs.append(draft.document)
        event(
            "parse_finished",
            name=name,
            ir_sha256=draft.document.content_digest(),
            published=draft.published,
        )
    if case_id == "k3e-table":
        raw = fixture_path("table-ir.json").read_bytes()
        sources.append(
            dict(name="table-ir.json", logical="table", hex=raw.hex(), sha256=digest(raw))
        )
        (directory / "table-ir.json").write_bytes(raw)
        docs.append(DocumentIR.model_validate_json(raw))
    records = {d.logical_document_id: release_inputs(d) for d in docs}
    inputs = dict(
        case_id=case_id,
        sources=sources,
        initial_governance={
            k: [x.model_dump(mode="json") for x in row] for k, row in records.items()
        },
    )
    before = digest(canonical([d.model_dump(mode="json") for d in docs]))

    class Ledger:
        async def read_current(self, *, tenant_id, logical_document_id, checked_at):
            row = records[logical_document_id]
            result = GovernanceRead(
                authority=AuthoritySnapshot(checked_at=checked_at, acl=row[0], withdrawal=row[1]),
                manifest=row[2],
            )
            event(
                "ledger_read",
                tenant_id=tenant_id,
                logical_document_id=logical_document_id,
                checked_at=checked_at.isoformat(),
                result=result.model_dump(mode="json"),
            )
            return result

    class Provider:
        def __init__(self, base, route):
            self.base, self.route, self.version = base, route, base.version

        async def rank(self, question, candidates, limit):
            event(
                "provider_started",
                route=self.route,
                version=self.version,
                question=question,
                limit=limit,
                candidates=[c.model_dump(mode="json") for c in candidates],
            )
            result = await self.base.rank(question, candidates, limit)
            event(
                "provider_finished",
                route=self.route,
                result=[r.model_dump(mode="json") for r in result],
            )
            if case_id == "k3e-withdrawal" and self.route == "lexical":
                previous = records["a"][1]
                updated = WithdrawalRecord.model_validate(
                    {**previous.model_dump(), "withdrawn": True, "revision": 2}
                )
                records["a"][1] = updated
                event(
                    "authority_mutation",
                    document="a",
                    before=previous.model_dump(mode="json"),
                    after=updated.model_dump(mode="json"),
                )
            return result

    catalog = InMemoryCatalog(tuple(docs))
    base_resolver = InMemoryBlockResolver(catalog)

    class Resolver:
        async def resolve(self, key):
            event("resolver_started", key=key.model_dump(mode="json"))
            result = await base_resolver.resolve(key)
            event(
                "resolver_finished",
                key=key.model_dump(mode="json"),
                block=result.model_dump(mode="json") if result else None,
            )
            return result

    service = KnowledgeRetrievalService(
        catalog,
        Ledger(),
        Resolver(),
        Provider(
            DeterministicRankProvider(
                tuple(key_for(d, b.block_id) for d in docs for b in d.blocks)
            ),
            "vector",
        )
        if case_id == "k3e-withdrawal"
        else None,
        Clock(),
        lexical=Provider(LocalBM25(), "lexical"),
    )

    async def invoke(operation, params):
        nonlocal active_request
        request = TrustedRetrievalRequest(
            request_id=case_run_id + "-" + str(len(calls)),
            tenant_id="tenant-eval",
            user_id="reader",
            effective_at=NOW,
            scope=("synthetic-plant",),
        )
        active_request = request.request_id
        event(
            "api_started",
            operation=operation,
            request=request.model_dump(mode="json"),
            params=params.model_dump(mode="json"),
        )
        packet = await getattr(service, operation)(request, params)
        result = dict(
            operation=operation,
            request=request.model_dump(mode="json"),
            params=params.model_dump(mode="json"),
            packet=packet.model_dump(mode="json"),
        )
        calls.append(result)
        event(
            "api_finished",
            operation=operation,
            request_id=request.request_id,
            packet_sha256=digest(canonical(result["packet"])),
        )
        active_request = None
        return packet

    def selector(key):
        return ClauseSelector(**{k: v for k, v in key.model_dump().items() if k != "tenant_id"})

    try:
        if case_id == "k3e-table":
            await invoke(
                "query_table",
                TableParams(
                    selector=selector(key_for(docs[0], "table")),
                    filters=(CellFilter(column=1, op="ge", value="10", expected_unit="m"),),
                ),
            )
        else:
            packet = await invoke(
                "search",
                SearchParams(
                    question="power inspection",
                    mode="hybrid" if case_id == "k3e-withdrawal" else "lexical",
                    top_k=1,
                ),
            )
            target = (
                key_for(docs[0], docs[0].blocks[0].block_id)
                if case_id == "k3e-withdrawal"
                else packet.items[0].key
                if packet.items
                else None
            )
            if target is not None:
                await invoke("get_clause", ClauseParams(selector=selector(target)))
            else:
                errors.append("missing_search_hit")
    except asyncio.CancelledError:
        event("case_finished", case_id=case_id, errors=["cancelled"])
        with (directory / "trace.jsonl").open("x", encoding="utf-8") as stream:
            for item in events:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
        raise
    except Exception as exc:
        errors.append("native_exception:" + type(exc).__name__)
    event("case_finished", case_id=case_id, errors=errors)
    diagnostics = dict(
        inputs_unchanged=before == digest(canonical([d.model_dump(mode="json") for d in docs]))
    )
    if case_id == "k3e-normal":
        diagnostics["source_and_quote_match"] = bool(
            len(calls) == 2
            and calls[1]["packet"]["items"]
            and calls[1]["packet"]["items"][0]["source_text"]
            == bytes.fromhex(sources[0]["hex"]).decode().splitlines(keepends=True)[0]
        )
    observation = Observation.model_validate(
        dict(
            schema_version="knowledge-evaluation-observation-v1",
            eval_run_id=eval_run_id,
            case_run_id=case_run_id,
            case_id=case_id,
            manifest_sha256=manifest_sha,
            input_content_sha256=digest(canonical(inputs)),
            inputs=inputs,
            drafts=drafts,
            documents=[d.model_dump(mode="json") for d in docs],
            calls=calls,
            events=events,
            diagnostics=diagnostics,
            errors=errors,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
    ).model_dump(mode="json")
    write_report(directory / "input.json", inputs)
    write_report(directory / "observation.json", observation)
    with (directory / "trace.jsonl").open("x", encoding="utf-8") as stream:
        for e in events:
            stream.write(json.dumps(e, ensure_ascii=False) + "\n")

    def ref(name):
        path = directory / name
        return dict(path=path.relative_to(root).as_posix(), sha256=digest(path.read_bytes()))

    return observation, dict(
        case_id=case_id,
        case_run_id=case_run_id,
        input=ref("input.json"),
        observation=ref("observation.json"),
        trace=ref("trace.jsonl"),
        sources=[ref(s["name"]) for s in sources],
    )


async def run_knowledge_suite(catalog_path, artifacts_root):
    from .knowledge_scoring import score_knowledge_observation

    catalog = load_catalog(catalog_path)
    for name, logical in [("normal.txt", "normal"), ("revoked-a.txt", "a"), ("allowed-b.txt", "b")]:
        parse_source(fixture_path(name).read_bytes(), name, logical)
    DocumentIR.model_validate_json(fixture_path("table-ir.json").read_bytes())
    root = Path(artifacts_root).resolve() / str(uuid4())
    if root.is_relative_to(FIXTURES.resolve()):
        raise ValueError("output inside trusted input root")
    root.mkdir(parents=True, exist_ok=False)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    versions = dict(
        head=git("rev-parse", "HEAD"),
        dirty=bool(git("status", "--porcelain")),
        python=platform.python_version(),
        file_hashes={
            p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
            for folder in ("src/anlan/evaluation", "src/anlan/knowledge")
            for p in (ROOT / folder).rglob("*.py")
        },
        fixture_hashes={
            p.name: digest(fixture_path(p.name).read_bytes())
            for p in FIXTURES.iterdir()
            if p.is_file()
        },
        lock_sha256=digest((ROOT / "uv.lock").read_bytes()),
        scorer="knowledge-observation-scorer-v1",
    )
    versions["file_hashes"]["evals/evaluate_knowledge_v2.py"] = digest(
        (ROOT / "evals/evaluate_knowledge_v2.py").read_bytes()
    )
    manifest = Manifest.model_validate(
        dict(
            schema_version="enterprise-eval-v2",
            code_version=versions["head"] + "+dirty" if versions["dirty"] else versions["head"],
            prompt_version="not_applicable:no-model",
            model_version="not_applicable:no-model",
            knowledge_version="K1-K2a-K3a-synthetic",
            dataset_version="knowledge-runner-v1-seen",
            scorer_version="enterprise-scorer-v2.0",
            environment="local Python " + platform.python_version(),
            run_at=datetime.now(UTC),
            fixed_at=NOW,
            request_limit=0,
            request_attempts=0,
            required_case_ids=catalog.cases,
        )
    ).model_dump(mode="json")

    def save(name, value):
        write_report(root / name, value)
        return dict(path=name, sha256=digest((root / name).read_bytes()))

    index = dict(
        schema_version="knowledge-evaluation-index-v1",
        eval_run_id=root.name,
        artifact_dir=str(root),
        status="partial",
        catalog=catalog.model_dump(mode="json"),
        versions=versions,
        manifest=save("manifest.json", manifest),
        cases=[],
        bundle=None,
        report=None,
    )
    rows = []
    try:
        for case_id in catalog.cases:
            observation, entry = await execute_knowledge_case(
                case_id, root, root.name, index["manifest"]["sha256"]
            )
            index["cases"].append(entry)
            rows.append(score_knowledge_observation(observation, entry["observation"]))
        bundle = dict(manifest=manifest, cases=rows)
        index["bundle"] = save("bundle.json", bundle)
        index["report"] = save("report.json", evaluate_bundle(bundle))
        index["status"] = "complete"
    finally:
        save("run-index.json", RunIndex.model_validate(index).model_dump(mode="json"))
    result = verify_knowledge_run(root / "run-index.json")
    if not result["valid"]:
        raise ValueError(str(result["errors"]))
    return index


def verify_knowledge_run(path):
    from .knowledge_verification import verify_knowledge_run as verify

    return verify(path)
