"""Dependency-first scoring of actual K2/K3 observations, never semantic gold."""

import json
from datetime import datetime
from decimal import Decimal

from anlan.knowledge.documents.contracts import DocumentIR
from anlan.knowledge.retrieval.catalog import InMemoryCatalog
from anlan.knowledge.retrieval.contracts import (
    CandidateText,
    ClauseParams,
    EvidenceKey,
    EvidencePacket,
    GovernanceRead,
    RankedKey,
    SearchParams,
    TableParams,
    TrustedRetrievalRequest,
)
from anlan.knowledge.retrieval.ranking import validate_ranked

from .contracts import SAFETY_CHECKS, CaseResult
from .knowledge_contracts import Observation, canonical, digest


def validate_dependencies(obs):
    from .knowledge_runner import NOW, parse_source, release_inputs

    inputs = obs.inputs
    if (
        inputs.get("case_id") != obs.case_id
        or digest(canonical(inputs)) != obs.input_content_sha256
    ):
        raise ValueError("input binding mismatch")
    docs = []
    drafts = []
    expected_names = {
        "k3e-normal": [("normal.txt", "normal")],
        "k3e-withdrawal": [("revoked-a.txt", "a"), ("allowed-b.txt", "b")],
        "k3e-table": [("table-ir.json", "table")],
    }[obs.case_id]
    if [(s["name"], s["logical"]) for s in inputs["sources"]] != expected_names:
        raise ValueError("missing or unexpected raw source")
    for source in inputs["sources"]:
        raw = bytes.fromhex(source["hex"])
        if digest(raw) != source["sha256"]:
            raise ValueError("source bytes mismatch")
        if obs.case_id == "k3e-table":
            docs.append(DocumentIR.model_validate_json(raw))
        else:
            draft = parse_source(raw, source["name"], source["logical"])
            drafts.append(draft.model_dump(mode="json", exclude={"raw_bytes"}))
            docs.append(draft.document)
    if obs.drafts != drafts or obs.documents != [d.model_dump(mode="json") for d in docs]:
        raise ValueError("actual parse/draft/IR mismatch")
    records = {d.logical_document_id: release_inputs(d) for d in docs}
    if inputs["initial_governance"] != {
        k: [x.model_dump(mode="json") for x in row] for k, row in records.items()
    }:
        raise ValueError("invalid synthetic release/authority stimulus")
    events = [e.model_dump(mode="json") for e in obs.events]
    if (
        not events
        or [e["seq"] for e in events] != list(range(len(events)))
        or events[0]["kind"] != "case_started"
        or events[-1]["kind"] != "case_finished"
        or any(
            (e["eval_run_id"], e["case_run_id"], e["case_id"])
            != (obs.eval_run_id, obs.case_run_id, obs.case_id)
            for e in events
        )
    ):
        raise ValueError("trace boundary/sequence binding mismatch")
    expected_ops = ["query_table"] if obs.case_id == "k3e-table" else ["search", "get_clause"]
    if [c["operation"] for c in obs.calls] != expected_ops:
        raise ValueError("missing native API calls")
    packets = []
    catalog = InMemoryCatalog(tuple(docs))
    for n, call in enumerate(obs.calls):
        request = TrustedRetrievalRequest.model_validate_json(canonical(call["request"]))
        if (
            request.request_id != obs.case_run_id + "-" + str(n)
            or request.tenant_id != "tenant-eval"
            or request.user_id != "reader"
            or request.effective_at != NOW
            or request.scope != ("synthetic-plant",)
        ):
            raise ValueError("untrusted request binding")
        {"search": SearchParams, "get_clause": ClauseParams, "query_table": TableParams}[
            call["operation"]
        ].model_validate_json(canonical(call["params"]))
        if call["operation"] != "search":
            target = (
                packets[0].items[0].key
                if obs.case_id == "k3e-normal" and packets and packets[0].items
                else None
            )
            if target is None:
                from anlan.knowledge.retrieval.contracts import key_for

                target = key_for(docs[0], docs[0].blocks[0].block_id)
            expected_selector = {
                k: v for k, v in target.model_dump(mode="json").items() if k != "tenant_id"
            }
            if call["params"]["selector"] != expected_selector:
                raise ValueError("selected source not bound to scenario/actual search")
        if call["operation"] == "search" and call["params"] != SearchParams(
            question="power inspection",
            top_k=1,
            mode="hybrid" if obs.case_id == "k3e-withdrawal" else "lexical",
        ).model_dump(mode="json"):
            raise ValueError("search stimulus mismatch")
        if call["operation"] == "query_table":
            expected_filter = [{"column": 1, "op": "ge", "value": "10", "expected_unit": "m"}]
            if call["params"]["filters"] != expected_filter or call["params"]["row_limit"] != 10:
                raise ValueError("table filter stimulus mismatch")
        packet = EvidencePacket.model_validate_json(canonical(call["packet"]))
        if packet.tokenizer_version != "cjk-bigram-asciiword-v1":
            raise ValueError("tokenizer version mismatch")
        if (
            packet.request_id != request.request_id
            or packet.operation != call["operation"]
            or packet.catalog_revision != catalog.revision
            or packet.effective_at != request.effective_at
            or packet.requested_at != NOW
            or packet.finished_at != NOW
        ):
            raise ValueError("packet request/version mismatch")
        for item in packet.items:
            pair = catalog.lookup(item.key)
            if pair is None:
                raise ValueError("packet key outside catalog")
            doc, block = pair
            if (
                item.source_text != block.source_text
                or item.title != doc.title
                or item.source_uri != doc.source_uri
                or item.locator != block.locator
                or item.source_sha256 != doc.source_sha256
                or item.ir_sha256 != doc.content_digest()
                or item.lineage != doc.lineage
                or item.table != block.table
                or item.generation != doc.generation
            ):
                raise ValueError("packet source binding mismatch")
        packets.append(packet)
    active = None
    call_no = 0
    pending_provider = None
    pending_resolver = None
    mutation = None
    provider_routes = []
    parse_records = []
    ledger_reads = 0
    api_provider_versions = []
    api_reads = 0
    api_resolves = 0
    latest_reads = {}
    resolved_blocks = {}
    for event in events[1:-1]:
        kind, data = event["kind"], event["data"]
        if kind == "api_started":
            if active is not None or call_no >= len(obs.calls):
                raise ValueError("invalid API start")
            call = obs.calls[call_no]
            if any(data.get(k) != call[k] for k in ("operation", "request", "params")):
                raise ValueError("API payload mismatch")
            active = call["request"]["request_id"]
            api_provider_versions = []
            api_reads = api_resolves = 0
            latest_reads = {}
            resolved_blocks = {}
            if event["request_id"] != active:
                raise ValueError("API start request binding mismatch")
        elif kind == "api_finished":
            call = obs.calls[call_no]
            if (
                active != data.get("request_id")
                or event["request_id"] != active
                or data.get("operation") != call["operation"]
                or digest(canonical(call["packet"])) != data.get("packet_sha256")
                or pending_provider
                or pending_resolver
                or list(packets[call_no].provider_versions) != api_provider_versions
                or api_reads != packets[call_no].authority_reads
                or api_reads == 0
                or api_resolves != packets[call_no].projection_reads
            ):
                raise ValueError("API finish mismatch")
            for item in packets[call_no].items:
                key_bytes = canonical(item.key.model_dump(mode="json"))
                read = latest_reads.get(item.key.logical_document_id)
                if (
                    key_bytes not in resolved_blocks
                    or read is None
                    or read.authority is None
                    or read.manifest is None
                    or read.authority.acl is None
                    or read.authority.withdrawal is None
                    or item.release_fingerprint
                    != digest(canonical(read.manifest.model_dump(mode="json")))
                    or item.checked_at != read.authority.checked_at
                    or item.acl_revision != read.authority.acl.revision
                    or item.withdrawal_revision != read.authority.withdrawal.revision
                ):
                    raise ValueError("missing resolver or current release/authority binding")
            active = None
            call_no += 1
        elif kind.startswith("parse_"):
            if active is not None or event["request_id"] is not None:
                raise ValueError("parse during retrieval")
            parse_records.append((kind, data))
        else:
            if active is None or event["request_id"] != active:
                raise ValueError("native event outside API")
            if kind == "ledger_read":
                read = GovernanceRead.model_validate_json(canonical(data["result"]))
                logical = data["logical_document_id"]
                row = records[logical]
                if (
                    data["tenant_id"] != "tenant-eval"
                    or read.manifest != row[2]
                    or read.authority is None
                    or read.authority.acl != row[0]
                    or read.authority.withdrawal != row[1]
                    or read.authority.checked_at != NOW
                    or datetime.fromisoformat(data["checked_at"]) != read.authority.checked_at
                ):
                    raise ValueError("ledger snapshot mismatch")
                ledger_reads += 1
                api_reads += 1
                latest_reads[logical] = read
            elif kind == "provider_started":
                if pending_provider is not None:
                    raise ValueError("overlapping providers")
                candidates = tuple(
                    CandidateText.model_validate_json(canonical(c)) for c in data["candidates"]
                )
                if data["question"] != "power inspection" or data["limit"] != 20:
                    raise ValueError("rank request mismatch")
                expected_version = {
                    "lexical": "bm25-k3a/1",
                    "vector": "deterministic-rank-fixture/1",
                }.get(data["route"])
                if data.get("version") != expected_version:
                    raise ValueError("provider version mismatch")
                api_provider_versions.append(expected_version)
                for c in candidates:
                    pair = catalog.lookup(c.key)
                    if pair is None or pair[1].retrieval_text != c.retrieval_text:
                        raise ValueError("rank input source mismatch")
                pending_provider = (data["route"], candidates)
                provider_routes.append((event["seq"], data))
            elif kind == "provider_finished":
                if pending_provider is None or pending_provider[0] != data["route"]:
                    raise ValueError("rank pairing mismatch")
                result = tuple(RankedKey.model_validate_json(canonical(r)) for r in data["result"])
                validate_ranked(result, pending_provider[1], 20)
                pending_provider = None
            elif kind == "authority_mutation":
                if obs.case_id != "k3e-withdrawal" or mutation is not None or pending_provider:
                    raise ValueError("unexpected mutation")
                before = records["a"][1]
                from anlan.knowledge.governance.policy import WithdrawalRecord

                after = WithdrawalRecord.model_validate_json(canonical(data["after"]))
                if (
                    data["document"] != "a"
                    or data["before"] != before.model_dump(mode="json")
                    or after
                    != WithdrawalRecord.model_validate(
                        {**before.model_dump(), "withdrawn": True, "revision": 2}
                    )
                ):
                    raise ValueError("invalid withdrawal transition")
                records["a"][1] = after
                mutation = event["seq"]
            elif kind == "resolver_started":
                if pending_resolver is not None:
                    raise ValueError("overlapping resolve")
                pending_resolver = data["key"]
                api_resolves += 1
            elif kind == "resolver_finished":
                if pending_resolver != data["key"]:
                    raise ValueError("resolve pairing mismatch")
                resolved_key = EvidenceKey.model_validate_json(canonical(data["key"]))
                pair = catalog.lookup(resolved_key)
                if pair is None or data.get("block") != pair[1].model_dump(mode="json"):
                    raise ValueError("resolver returned wrong source block")
                resolved_blocks[canonical(data["key"])] = data["block"]
                pending_resolver = None
            else:
                raise ValueError("unexpected native event")
    if (
        active is not None
        or call_no != len(obs.calls)
        or pending_provider
        or pending_resolver
        or not ledger_reads
    ):
        raise ValueError("incomplete native event chain")
    if len(parse_records) != len(drafts) * 2:
        raise ValueError("missing parse events")
    for i, source in enumerate(inputs["sources"] if drafts else []):
        start, end = parse_records[2 * i : 2 * i + 2]
        if start != (
            "parse_started",
            {"name": source["name"], "sha256": source["sha256"]},
        ) or end != (
            "parse_finished",
            {"name": source["name"], "ir_sha256": docs[i].content_digest(), "published": False},
        ):
            raise ValueError("parse event payload mismatch")
    if obs.case_id == "k3e-withdrawal":
        if (
            [d["route"] for _, d in provider_routes] != ["lexical", "vector"]
            or mutation is None
            or not provider_routes[0][0] < mutation < provider_routes[1][0]
        ):
            raise ValueError("missing two-route withdrawal stimulus")
        if {c["key"]["logical_document_id"] for c in provider_routes[0][1]["candidates"]} != {
            "a",
            "b",
        }:
            raise ValueError("lexical never saw both documents")
    elif obs.case_id == "k3e-normal":
        if [d["route"] for _, d in provider_routes] != ["lexical"]:
            raise ValueError("missing real lexical route")
    elif provider_routes:
        raise ValueError("unexpected table ranking")
    return packets, provider_routes


def score_knowledge_observation(raw, evidence_ref):
    obs = Observation.model_validate(raw)

    def check(status, reason, pointer="/calls"):
        return dict(
            status=status,
            evidence=json.dumps(
                dict(
                    case_id=obs.case_id,
                    case_run_id=obs.case_run_id,
                    **evidence_ref,
                    json_pointer=pointer,
                    reason=reason,
                    scorer_rule_version="knowledge-observation-scorer-v1",
                ),
                sort_keys=True,
            ),
        )

    safety = {name: check("pending", "Control not exercised") for name in SAFETY_CHECKS}
    errors = list(obs.errors)
    structure = check("pass", "Actual native packet contracts valid")
    try:
        for call in obs.calls:
            EvidencePacket.model_validate_json(canonical(call["packet"]))
    except (ValueError, TypeError, KeyError):
        structure = check("fail", "Invalid actual packet contract")
        errors.append("native_schema_invalid")
    try:
        if structure["status"] == "fail":
            raise ValueError("invalid packet")
        packets, routes = validate_dependencies(obs)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        errors.append("observation_integrity:" + type(exc).__name__)
    else:
        if not obs.diagnostics.get("inputs_unchanged"):
            errors.append("inputs_changed")
        if obs.case_id == "k3e-normal":
            ok = (
                len(packets[0].items) == len(packets[1].items) == 1
                and packets[0].items[0].key == packets[1].items[0].key
                and packets[1].items[0].locator.line_start == 1
                and obs.diagnostics.get("source_and_quote_match") is True
            )
            if not ok:
                errors.append("literal_quote_or_selection_mismatch")
        elif obs.case_id == "k3e-withdrawal":
            vector = routes[1][1]["candidates"]
            from anlan.knowledge.retrieval.contracts import key_for

            revoked_doc = DocumentIR.model_validate_json(canonical(obs.documents[0]))
            revoked_keys = {key_for(revoked_doc, b.block_id) for b in revoked_doc.blocks}
            revoked_digests = {digest(canonical(k.model_dump(mode="json"))) for k in revoked_keys}
            leaked_refs = any(
                any(issue.related_key in revoked_keys for issue in packet.issues)
                or any(event.key_digest in revoked_digests for event in packet.audit)
                or any(key in revoked_keys for item in packet.items for key in item.required_keys)
                or any(row.table_key in revoked_keys for row in packet.table_rows)
                for packet in packets
            )
            clean = (
                {c["key"]["logical_document_id"] for c in vector} == {"b"}
                and all(i.key.logical_document_id == "b" for i in packets[0].items)
                and not packets[1].items
                and not packets[1].table_rows
                and "authorization_changed" in {i.code for i in packets[0].issues}
                and not leaked_refs
            )
            safety["invalid_knowledge"] = check(
                "pass" if clean else "fail",
                "Measured withdrawal at provider and output boundaries",
                "/events",
            )
            if not clean:
                errors.append("withdrawn_evidence_reached_consumer")
        else:
            packet = packets[0]
            rows = packet.table_rows
            ok = (
                len(rows) == 1
                and rows[0].row_index == 0
                and len(rows[0].cells) == 2
                and rows[0].cells[1].value == "10"
                and Decimal(rows[0].cells[1].value) >= Decimal("10")
                and rows[0].cells[1].locator.cell == "B3"
                and rows[0].cells[1].locator.derivation == "derived_from_reviewed_ir"
                and len(packet.items) == 1
                and packet.items[0].table.units == ("", "m")
                and packet.items[0].table.footnotes == ("SYNTHETIC fixture footnote",)
            )
            if ok:
                table = packet.items[0].table
                expected_values = table.rows[0]
                ok = (
                    rows[0].table_key == packet.items[0].key
                    and tuple(cell.value for cell in rows[0].cells) == expected_values
                    and all(
                        cell.locator.model_dump(mode="json")
                        == {
                            "schema_version": "knowledge.table-cell.v1",
                            "sheet": "SYNTHETIC",
                            "cell": ("A3", "B3")[n],
                            "data_row": 0,
                            "column": n,
                            "derivation": "derived_from_reviewed_ir",
                        }
                        for n, cell in enumerate(rows[0].cells)
                    )
                )
            if not ok:
                errors.append("table_selection_mismatch")
    if not obs.calls:
        structure = check("pending", "No actual native result")
    return CaseResult.model_validate(
        dict(
            case_id=obs.case_id,
            origin="SYNTHETIC",
            split="seen_regression",
            slice=obs.case_id,
            severity="critical",
            structure=structure,
            semantic=check("pending", "Free-text semantic support not measured"),
            semantic_source="not_measured",
            human=check("pending", "No human review"),
            human_reviewer=None,
            safety=safety,
            errors=sorted(set(errors)),
            latency_ms=obs.elapsed_ms,
            cost_usd=None,
            total_tokens=None,
        )
    ).model_dump(mode="json")
