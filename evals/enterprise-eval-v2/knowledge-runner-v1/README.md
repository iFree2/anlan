# Knowledge runner v1 — three seen synthetic integration scenarios

Only these inputs are trusted by this runner. Catalog/fixture paths must resolve inside this fixed repository directory; arbitrary catalog parents do not grant access. Inputs contain no scores.

- `normal.txt`: real UTF-8 bytes with CRLF, blank line and LF. Native parse_txt produces an unpublished needs_review draft; independently constructed SYNTHETIC policy records permit native K3 search and get_clause.
- `revoked-a.txt` / `allowed-b.txt`: native TXT parsing and LocalBM25; after lexical completes, the synthetic authority ledger withdraws A. Native K3 rebuilds candidates before the explicit deterministic vector rank fixture. Later get_clause on A must remain denied.
- `table-ir.json`: independent SYNTHETIC rectangular XLSX-shaped IR fixture, not output from TXT parsing or a real workbook reader. Native query_table uses Decimal filtering and returns `B3` with `derived_from_reviewed_ir`, retaining headers, units and footnote.

Policy `approved` / `SYNTHETIC-evaluation-fixture` records only stimulate governance. Drafts stay unpublished, lineage quality stays unverified, E1 human and free-text semantic scores stay pending. The vector provider is a rank fixture, not embedding inference.

Run from repository root with a fresh local output root:

```powershell
uv run --no-sync python evals/evaluate_knowledge_v2.py --catalog evals/enterprise-eval-v2/knowledge-runner-v1/cases.json --artifacts-dir <new-local-output-root>
```

Exit 0 means the finite-sample gate passed, 2 means complete execution with pending/blocked gate, and 1 means input/output/integrity failure. Each run uses a new UUID directory and exclusive file creation. Output must be outside this input directory.

The E1 manifest keeps its original strict fields. A separate strict run-index records source/lock/fixture versions and file hashes. Cases preserve raw bytes, actual draft/IR, independent authority snapshots, provider inputs/results, resolver blocks, API requests and EvidencePackets. Local trace events bind case/run/request/sequence and payload; there is no OTLP/network exporter.

Verification checks raw input and source/version bindings, per-request current ledger and resolver counts/results, mutation order and all revoked-reference surfaces, then re-scores observations and compares every saved case before re-aggregating the E1 report. Rehashing a modified bundle/report cannot erase an observed error. Hashes do not authenticate a malicious trusted host that rewrites all inputs and observations.

Expected clean suite gate is pending: structure is measured; only the explicitly exercised withdrawal control may pass. Other safety controls, human review, semantics, tokens and cost remain pending/null. Local measured latency excludes final scoring/report serialization and is not model/production latency. Old E2 sources and historical artifacts are retained unchanged.
