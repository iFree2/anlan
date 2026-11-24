# K3→E1 最小真实离线集成评测设计

日期：2026-11-17（Asia/Shanghai）。状态：**D 待审，仅设计；尚未新增运行器源码、测试或场景文件，未运行拟议测试。**

本窗口检查点：E1/E2a 已交付并冻结，M2 审查问题已转交对应窗口，本包不再修 M2。应用 brainstorming / writing-plans 方法核对现有接口、比较方案并细化验收。当前只新增本文件；父窗口 D 审通过并触发后才进入 TDD，不新建聊天/分支，不 stage/commit，不回退他人改动。

**Goal:** 用实际合成原文 bytes 经 K2a/K1/K3 原生 API 执行，保存证据和撤回时序，逐例生成 E1 报告并支持从原始观测重评分；首包固定三个已见合成场景。

**Architecture:** 独立 knowledge-runner-v1 输入与产物，原生调用 + 只做转发/记录的治理与 provider 包装器；保持旧 runner-v1 的合同、实现和产物完全不变。E1 Manifest 原字段不扩展，丰富版本/trace/hash 放新严格 sidecar，验证执行依赖后才给有限安全评分。

**Tech Stack:** Python 3.13、现有 Pydantic/pytest、标准库 hashlib/json/decimal/time、K2a parse_txt、K1 治理、K3 内存目录/本地 BM25/排名替身。零真实模型、embedding、网络、PG、云和部署；无新增依赖或 SQL。

## 1. 当前源码事实与不能伪造的边界

已读 `knowledge-retrieval-design.md`（含最终 D 修订）、K2a parsing/text.py/contracts.py/_text_source.py、K1 documents/contracts.py/governance/policy.py、K3 retrieval/contracts.py/catalog.py/providers.py/service.py 及当前相邻测试；未仅凭旧设计中“尚未实现”的历史描述推断接口不存在。

当前实际签名：

- `parse_txt(raw: bytes, *, filename: str, metadata: TxtIngestMetadata, candidate: SourceCandidate) -> TxtIngestDraft`。无文件/网络/发布副作用。draft 必须 needs_review/published=False；原始 CRLF/LF/CR 与物理行号保存，空行省略块但不删原 bytes；block_id 来自实际行号和行字节摘要。
- `InMemoryCatalog(documents: tuple[DocumentIR, ...])`，拒绝重复，保存完整 IR 摘要及 catalog.revision。
- `KnowledgeRetrievalService(catalog, governance, resolver, vector, clock, *, lexical=None)`，`search(request, SearchParams)` / `get_clause(request, ClauseParams)` / `query_table(request, TableParams)` 均 async 返回 EvidencePacket。
- GovernanceSource `read_current(*, tenant_id, logical_document_id, checked_at) -> GovernanceRead`。每次读取独立权威状态，不从 draft/目录回推 ACL/撤回。
- RankProvider `version` 与 `rank(question, candidates, limit)`；默认 lexical 为真实本地 LocalBM25，vector 可为空或 `DeterministicRankProvider`，后者明确不是 embedding。
- `EvidencePacket` 含宿主 request_id、operation、effective_at、catalog_revision、processor/tokenizer/provider 版本、items/table_rows/issues/audit/计数。items.source_text 是 IR 原文，不用 retrieval_text 代替引用。
- query_table 正向物理定位只支持 XLSX 格式的**合成矩形 IR**；CellLocation.derivation=`derived_from_reviewed_ir`，不代表重新读取原 XLSX。

**关键范围决策：** K2a 当前不能把 TXT 解析成表格，也没有 XLSX 导入器。首包三场景中，两个文本场景覆盖实际 TXT bytes→parse_txt→显式合成发布/独立权威→K3→证据→E1；表格场景从单独合成结构 IR 进入同一 K1/K3→E1 后半链。不得给 TXT 强换 source_format=xlsx 或编造 parser_lineage 以声称三场景都来自 TXT。若后续要求 XLSX 实际 bytes→解析→筛选，需另包解析能力与授权，不能本包补写 K 源码。

“合成审核 manifest”只用于刺激策略：review_status=approved、reviewer='SYNTHETIC-evaluation-fixture'；draft 本身依旧 needs_review/published=False，不被改写成已发布，Lineage.quality 仍 unverified。E1 human=pending、人类 reviewer=null。公开或真实企业资料、法规效力、真人金标、真实检索泛化质量均不在本包结论内。

## 2. 方案选择

1. **采用：独立原生知识链运行器。** 新目录/CLI/观测合同和评分器，通过当前 K API 执行；可复用 E1 的 evaluate_bundle/write_report，不修改旧 E2。能独立审查输入→执行→观测→评分因果。
2. 扩展旧 runner-v1 的固定八场景和 Catalog enum：会改变冻结合同及其历史产物解释，拒绝。
3. 导入 K 单元测试 harness 或直接读其已保存分数：会耦合测试实现、无法证明集成入口实际执行，拒绝；本包包装器只调用生产 API，不 import tests。

目录内不接受预制 score/safety pass、任意 Python/SQL/脚本、URL 下载、模型配置或跳过校验开关。expected 表示独立且版本化的工程谓词，不直接成为实际结果。

## 3. 所有权与拟定接口

| 新文件/目录 | 职责 |
|---|---|
| `src/anlan/evaluation/knowledge_runner.py` | 新入口编排、固定可信根、原生调用、隔离和独占产物 |
| `src/anlan/evaluation/knowledge_contracts.py` | 严格三场景目录、输入、observations、事件、run-index 合同 |
| `src/anlan/evaluation/knowledge_scoring.py` | 依赖/结构/工程诊断、有限安全规则、Evidence 引用和重评分 |
| `src/anlan/evaluation/knowledge_verification.py` | hash/版本/case/request/事件载荷、重评分与重聚合校验 |
| `evals/evaluate_knowledge_v2.py` | 独立离线 CLI，既有入口不改 |
| `tests/test_enterprise_knowledge_evaluation.py` | 真原生链、反向篡改、只读隔离与 CLI 回归 |
| `evals/enterprise-eval-v2/knowledge-runner-v1/` | 冻结 catalog、实际 TXT bytes、合成 table-ir.json、README；仅输入 |
| `evals/enterprise-eval-v2/knowledge-runner-results/<eval_run_id>/` | 后续独占运行产物，位于输入根之外 |
| `docs/phases/engineering-20261116/knowledge-evaluation-report.md` | 实施后的真实验证及审查记录，本设计阶段不创建 |

不改 evaluation/runner*.py、offline_fixtures.py、scoring.py、E1 contracts/report、旧 evals/evaluate_enterprise.py、runner-v1 输入与历史产物；不修改任何 K/工具/工作流源码、旧测试/SQL/总文档。新增辅助文件只在 evaluation/ 内，责任如上，不跨包抽取“通用平台”。K3a 已由父窗口确认最终冻结（协调88 passed、独立88+10及Ruff；这些为父窗口证据，本窗口未重复运行），本设计可依赖当前接口；实施开始只核对冻结接口未变，不重做总蓝图；发现新 API 缺陷只报告所属窗口，不复制/替代其授权或检索算法。

拟定公开接口（本轮没有实现）：

- `async run_knowledge_suite(catalog_path: Path, artifacts_root: Path) -> KnowledgeRunIndex`：固定三场景全部执行，原始错误保留，request_limit/request_attempts=0。
- `async execute_knowledge_case(spec, context) -> KnowledgeObservation`：实际解析/构造策略输入/原生 K3 调用，不接受或生成预制评分。
- `score_knowledge_observation(spec, observation, evidence_ref) -> CaseResult`：只评分已保存原始观察，必须先验证场景刺激、输入内容摘要、原生调用/事件及实际返回合同。
- `verify_knowledge_run(index_path: Path) -> VerificationResult`：无需重发 API，基于保存输入/原始输出/trace 重新验证并逐例重评分，比较完整 bundle 后重聚合 E1 report。

固定可信输入根由 `knowledge_runner.py` 中宿主常量绑定到仓库 `evals/enterprise-eval-v2/knowledge-runner-v1/`。catalog 和每个引用 resolve 后都必须位于该根；拒绝绝对 fixture path、`..`、根外 symlink/reparse target、外部 URI。不能从任意 catalog.parent 自动推导授权根。输出根必须在输入根外，子目录 eval_run_id 用 mkdir(exist_ok=False)，每个文件独占创建。

## 4. 首包三个冻结场景与实际执行顺序

共同使用固定业务时点 `2026-11-17T00:00:00+00:00`，身份 tenant-eval/reader，scope=('synthetic-plant',)。请求 checked_at 来自宿主固定 UTC 测试时钟，时长用真实 time.monotonic/perf_counter，不把逻辑时钟推进当延迟。若场景时点变成多组，suite manifest.fixed_at=null，不强填某一组冒充全套时点。

### K3E-01：TXT 原文引用正常链

输入 `normal.txt` 保存实际 UTF-8 bytes，含 CRLF、空行和至少两条明确 SYNTHETIC 段落。例如首条为 `SYNTHETIC clause alpha: isolate power before inspection.\r\n`。问题为 `power inspection`，期望工程目标是物理第1行，不设人类风险语义金标。

执行顺序：

1. 实际读取允许根 bytes，保存 raw 字节副本/SHA256，构造严格 SourceCandidate（source_url 为 synthetic URI，expected_source_sha256 为实际摘要）和 TxtIngestMetadata。
2. 实际调用 parse_txt，保留 draft.json 与完整 DocumentIR；验证 draft 仍未审核发布、source_sha256 和每行 source_text/locator 与原 bytes 一致。
3. 对该实际 IR 新建独立合成 ReleaseManifest（绑定 content_digest/source/version/generation/scope/有效期）、ACLRecord、WithdrawalRecord，放进本例独立内存 ledger；不是修改 draft，也不伪造生产发布。
4. 建真实 InMemoryCatalog/InMemoryBlockResolver，包装真实 LocalBM25 只记录调用参数/返回，不改变排名。
5. 调用真实 `search`（lexical, top_k=1），然后用**实际返回命中**的 selector 调用真实 `get_clause`。若 search 无命中，记录空结果并给工程诊断失败，不从期望 selector 凭空补一次成功 get。
6. 保存两个完整 EvidencePacket，校验原文、实际行号/行末符、原字节 hash、IR digest、发布 fingerprint、request_id/effective_at/catalog_revision 和 provider 版本；任何标识错误不能作为有效引用。

工程诊断 `raw_quote_matches_physical_line`、`search_then_get_same_key`、`draft_unpublished`、`release_binds_actual_ir`。这些是确定性源文/引用一致性，不是自由文本主张语义正确率。

### K3E-02：lexical 与 vector 两路之间撤回

输入 `revoked-a.txt`、`allowed-b.txt` 都实际经 parse_txt；A/B 初始同租户同 scope 具有独立有效合成发布/权威记录，查询词明确在两者中。两个文档的原始字节、IR 和独立 ledger 都保存。

执行使用真实 LocalBM25 转发包装器和明确的 DeterministicRankProvider 转发包装器。lexical await 的实际返回值记录完毕、返回给 K3 之前，包装器只对 ledger 的 A WithdrawalRecord 做一次显式撤回（revision 1→2，withdrawn=True，updated_at<=随后 checked_at），记录 mutation 事件及前后摘要；不改服务、目录、IR、manifest 或 provider 结果。

随后完全由 K3 原生逻辑继续重读治理、重建 vector 语料。必须观察：

- lexical 实际见到 A/B；mutation 位于 lexical 结果产生与 vector 调用之间，有严格事件序号与 request_id。
- vector **实际输入**只含仍授权 B，A 的 key 和 retrieval_text 均不得出现；不能仅凭最终 packet 无 A 判定输入端防护通过。
- 返回 packet 的 items/table_rows/related_key/audit 不泄露撤回 A 的正文或可定位内容，issues 包含 authorization_changed；B 可继续保留，整体通常 incomplete。不预制“必然 evidence_found”标签。
- 新请求再以旧 A IR/同一旧 release 调用 get_clause，当前 ledger 仍已撤回，必须无 A items（通常 unknown/no_authorized_evidence）；不得重建全允许 ledger，也不把之前已返回的旧 packet 当新授权凭据。

工程诊断独立呈现 provider 输入隔离、最终证据移除、后续旧目录查询拒绝。这里 vector 是显式排名替身，不进行编码，不下载或调用 embedding 模型，不把 RRF 分数称为正确概率。

### K3E-03：合成矩形表 IR 的真实代码筛选

输入 `table-ir.json` 是单独明确 SYNTHETIC 的人工构造**结构夹具**（非人工领域审核），source_format=xlsx，Lineage.parser='synthetic-structured-fixture' / quality=unverified，source_uri 标注 synthetic。不存在原 XLSX 文件，source_sha256 是合成来源标识，不冒充读取了 workbook bytes。实际 JSON 字节摘要与 IR content_digest 另外记录。

矩形 A1:B4：两级 header，数据两行 `('item0','10')`、`('item1','9.9')`，units=('', 'm')，明确 SYNTHETIC footnote。source_text 含原始单元格字符串；表块带 SheetLocation。构造独立绑定该 IR 的合成 release/ACL/withdrawal，实际建目录并调用 `query_table`，CellFilter(column=1, op='ge', value='10', expected_unit='m')。

实际期望输出只含数据行0，值原字串 `'10'`、物理推导地址 B3，derivation 必须 derived_from_reviewed_ir，同时保留表块证据/source_text/headers/units/footnotes。不得把 B3 说成已从原 XLSX 验证，不能把“本范围无其他匹配”说成无风险。selector 精确匹配，表格路径无需调用 rank provider，provider 调用数应为0。

本场景工程表格诊断与 K2 TXT 链分开标记。不能为了形式上都经过 parse_txt 而加入无因果关系的 TXT 步骤。

## 5. 原始观测、版本与 trace

新 KnowledgeObservation/RunIndex 使用独立 schema Literal、extra=forbid、严格类型及唯一 IDs；不能让 extra 字段或 model_copy 绕过 native packet 校验。

每个运行目录包含：

- `manifest.json`：原 E1 Manifest 原字段；三 required case IDs，真实 run_at，固定业务时点、代码/prompt/model/knowledge/dataset/scorer 版本。prompt/model 用明确 not_applicable:no-model，不伪造 prompt 调用。
- `run-index.json`：eval_run_id、case_run_ids、suite/manifest 摘要、状态 complete/partial、文件引用；丰富 sidecar 版本包括 git HEAD/dirty、实际执行 evaluation/K1/K2a/K3 源码字节 SHA256、uv.lock/Python、parser/config/tokenizer/provider/scorer 版本、源字节和合成表 IR 摘要。E1 Manifest 不增字段。
- `cases/<id>/raw/*.txt`（文本例）或 `table-ir.json`（表格例）：本次实际输入字节的独占副本。
- `input.json`：严格场景参数、SourceCandidate/metadata、可信身份/业务时点、初始 ledger 与合成发布标识。
- `draft.json` / `documents.json`：原生 parse_txt 结果和完整 IR；raw_bytes 单独保存，draft 描述用 raw 引用/摘要，验证时重新 parse_txt，不用 JSON 编码暗改 CRLF。
- `observation.json`：顺序调用记录、真实返回/异常、完整 EvidencePackets、ledger read 返回快照、transition 前后、每次 provider 的真实候选/排名、resolver 的 key/返回摘要、源/目录/请求及父级 run 绑定、实际 elapsed_ms、错误归因。
- `trace.jsonl`：新版本本地顺序事件，不依赖旧 JsonlTrace/OTLP。producer='evaluation_knowledge_runner'，绑定 eval_run_id/case_run_id/case_id/request_id/api_call_id/operation/event_seq；api_started/api_finished、parse_started/finished、ledger_read、provider_started/finished、authority_mutation、resolver_started/finished、case_started/finished。事件引用相关实际输入/返回摘要和阶段，不伪造 K 服务已有 trace，也不输出隐藏思维链。
- `diagnostics.json`、`bundle.json`、`report.json`：独立工程诊断、由观测得到的 E1 CaseResult 与统一报告。每个 Check.evidence 用结构化 JSON 引用对应 observation/hash/case_run_id/json_pointer/scorer_rule_version。

K3 自带 packet.audit 单独保存并验证，不能拿它替代 wrapper 对 provider 输入和 ledger mutation 顺序的实际观测；其 audit 可裁剪/去标识，因此不要求每次 read 都在 packet.audit 有一一明文 ID。原生返回 requested_at/effective_at/catalog_revision/request_id 必须与具体 api_call 匹配，不能只校验外层 case/run 壳。

输入同时保存原字节摘要与 canonical JSON 内容摘要，避免 E2a 已遇到的 Windows CRLF/LF 重建误差。source_text 的换行比较仍按原 TXT bytes 解码的物理行原样进行，不使用 strip 后的字符串充当精确原文。

## 6. 评分与不可省略的依赖验证

评分前必须验证：场景目录 ID/family/stimulus、raw 文件摘要、input canonical 摘要、原生调用名称/参数/顺序、实际 draft/DocumentIR/GovernanceRead/EvidencePacket 合同、必需 ledger/provider/resolver/transition 观测及版本/request/case/run 绑定。缺依赖先 pending+integrity error；不能仅返回 allowed/reason/status 正好符合期望就给安全 pass。原生结构无效时保留结构 fail 与错误，不继续遍历畸形 items/table_rows 导致崩溃或丢后续例。

| E1 维度/安全项 | 本包口径 |
|---|---|
| structure | 对实际原生 draft/IR/packet/表格引用结构合同及必要包结构校验；与工程 expected 是否命中分开 |
| semantic | 全部 pending，semantic_source=not_measured；精确源文/数值筛选诊断不等于自由文本主张语义支持 |
| human | 全部 pending，reviewer=null；合成发布 reviewer 字段不可导入此处 |
| invalid_knowledge | **仅 K3E-02 明确撤回刺激**依赖齐全且 vector/终端/后续 get 均拒 A 时 pass；存在实际撤回后读取/输出泄漏 fail；缺观测 pending。正常/表格无失效制度刺激，保持 pending |
| unauthorized_access | 本包没有跨租户/越权刺激，保持 pending；不从正常同租户运行推导安全通过 |
| stale_revision | 没有事实旧 revision 刺激，保持 pending；正常版本一致只作 diagnostics |
| fabricated_facts / unsupported_certainty | 均 pending；引用存在/精确复制不等于主张支持，表值正确也不等于风险结论可靠 |
| approval/responsibility/alarm_mutation/alarm_chain_blocked | 均 pending；未接这些链路，不能用只读代码推断已实测 |

K3E-02 若 A 真出现在撤回后 vector 输入，安全 invalid_knowledge=fail，并独立列 blocker；即使最终 packet 已删除 A，也不能被平均质量掩盖。反过来 mutation 缺失、lexical 未实际见 A 或 vector 没有实际运行的记录，不给预期安全 pass。此首包为 A/B 两文档场景，要求 vector 至少调用一次且看见 B；“全部撤回导致零 vector 调用”另包扩例，不混入当前刺激。

工程 diagnostics：TXT 原字节/行号/引文字面一致；draft 未发布；合成 release 绑定实际 IR；本地 BM25 真被调用；search/get 同一 key；逐路当前治理/语料不复用；表格 Decimal 边界/行集/值/单位/脚注/derived locator；输入/目录在调用前后未变。这些不预制为 CaseResult.semantic pass。工程预期不符或 integrity error 写 CaseResult.errors，安全违规另写 safety fail；任意错误不会因“是注入预期”而被抹掉。

正常成功预计整体仍 pending（人工/语义/未测项）；如真实错误则 blocked。不得为使门禁通过填满安全 pass。请求数真实0，token/费用未测仍 null。每例 latency 为真实 local parse/装配/K 调用/观测阶段时间，明确截止点，不冒充真实 embedding/模型或生产端到端延迟。空/漏例、缺计量沿用 E1 的未知总量/分位数规则。

## 7. 校验器沿用已修复的因果门禁

`verify_knowledge_run` 必须执行以下流程，不只验证 bundle→report：

1. 独占目录内路径解析/摘要校验；严格 catalog/index/manifest；三例齐全、ID唯一、complete，partial 不通过。
2. 对文本原始 bytes 重新调用无副作用 parse_txt，比较完整 draft/IR/source/lineage，不重放 live 检索。表格只核对保存合成 IR 与独立 JSON 字节摘要，不“重新解析 XLSX”。
3. 校验合成发布与各时点权威 ledger 输入：实际 IR/content digest、scope/tenant/reader、有效区间、ACL/withdrawal revision；撤回 mutation 真的从 false→true/revision递增，旧 manifest/目录未随之改写。预期标签不足以替代这些输入。
4. 校验 trace 严格起止、连续唯一 event_seq、API 参数/返回摘要、解析与发布装配先后、ledger/provider/resolver 调用数及 payload；K3 两路之间撤回先后、vector 候选实际内容、后续 get 请求和 packet 均要绑定。made_up event/错 request_id/缺整路记录都拒绝。
5. 从每个保存 observation 与同一 spec/evidence_ref **重新 score**，逐例完整比较 bundle；再调用原 E1 evaluate_bundle 比较 report。改 errors/safety 后即使重算 bundle/report/index 摘要，也不能抹掉原始观测的错误。
6. 此门禁是内容完整性和可重算性，不是针对可信宿主恶意全盘重写原 bytes、所有观测和全部摘要的密码学认证。

## 8. 只读隔离、失败和取消

每例独立目录、IR、目录投影与可变 ledger。唯一状态变更是 K3E-02 显式的合成内存撤回事件；保存 transition，无持久化发布/ACL/数据库业务写入。其他输入、IR、目录和静态夹具前后摘要一致，原文件只读。不能把故意撤回也描述为整个运行没有任何内存状态变化。

只调用当前原生 API，不 monkeypatch K 全局函数、不注入假的 EvidencePacket、不复制 K 授权/检索算法；包装器仅记录并转发，撤回 hook 仅改测试 ledger。Lexical 包装真实 LocalBM25；vector 包装显式 DeterministicRankProvider，版本必须保留 fixture 含义。没有后台任务/缓存/模型 HTTP/OTLP/PG。

目录或任一静态输入损坏在任何原生执行前验证并 exit1，不做执行到一半才发现夹具不合法。原生运行异常保留原始异常固定类别和已得观测，生成该例 errors/pending，继续其余独立例；无效集合不引起评分崩溃。CancelledError 传播，保存 partial index/已有 trace，不制造完整报告；重跑必须用新 eval_run_id，不覆盖旧证据。

## 9. D 通过后的 TDD 步骤与命令

以下是**拟执行命令及预期失效点**，本轮没有执行这些新测试，不预填通过数。

- [ ] 严格目录与路径：新增 tests `test_catalog_rejects_precomputed_scores_and_duplicate_ids`、`test_fixture_root_not_catalog_parent`、`test_static_input_error_precedes_execution`。RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k 'catalog or fixture or static_input'`。缺运行器需在测试体明确失败，不用 importorskip 或 setup errors 伪造 RED。
- [ ] 真 TXT→K2/K1/K3：新增 `test_txt_bytes_parse_search_get_preserve_line_ending_and_draft_status`；断言真实 parse/localBM25/governance/resolver 调用及 source_text/line locator/hash/IR/release/request 绑定；RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k txt_bytes`。通过后只说明工程字面一致，不填语义/人工标签。
- [ ] 撤回输入边界：新增 `test_lexical_actual_return_then_withdrawal_before_vector_input`、`test_old_directory_get_after_withdrawal_stays_denied`、`test_no_mutation_or_missing_provider_trace_is_pending`。RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k 'withdrawal or mutation or provider_trace'`。不能只断言最终 packet 不含 A，必须断言 vector 的实际 CandidateText 和时序。
- [ ] 表格：新增 `test_table_decimal_filter_preserves_source_and_derived_b3`、`test_table_ir_not_claimed_as_parsed_workbook`。RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k table`。原生 table packet 真输出目标行/headers/units/footnote/derivation；schema 合法与筛选结果正确分开记录。
- [ ] 评分失败保留：新增 `test_invalid_packet_structure_cannot_get_safety_pass`、`test_missing_stimulus_cannot_get_safety_pass`、`test_malformed_items_do_not_abort_suite`、`test_unmeasured_controls_remain_pending`。RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k 'safety or malformed or unmeasured'`。人工构造的畸形观察只用于评分器负向测试，不冒充真实 API 返回证据。
- [ ] 因果/trace 篡改：新增 `test_rehashed_bundle_cannot_erase_observation_error`、`test_rehashed_safety_pass_cannot_bypass_rescore`、`test_forged_trace_shell_or_wrong_request_is_rejected`、`test_missing_rank_route_or_reordered_mutation_is_rejected`。RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k 'rehashed or forged or reordered'`。要真实生成一次产物，再篡改副本并重算被改文件摘要，不能只测试旧 hash 不匹配的简单情况。
- [ ] 隔离/CLI/旧冻结：新增 `test_cli_actual_three_scenarios_zero_external_io`、`test_cancel_propagates_partial_index`、`test_output_refuses_overwrite`、`test_old_runner_sources_and_fixture_artifacts_unchanged`。RED：`uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py -k 'cli or cancel or overwrite or unchanged'`。网络/PG连接在测试内设为触发即失败；不调用真实 embedding，测试不因缺 DSN 跳过。

每步真实观察 RED 后最小实现，再 GREEN/Ruff；对错误归因不符的测试先修装配，不把无效 import/环境异常当功能验收。若暴露 K 缺陷，保存复现并交父窗口，不能越权修 K 或将断言改成跳过。

拟最终命令：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py tests/test_enterprise_evaluation.py tests/test_enterprise_evaluation_runner.py tests/test_knowledge_v2_parsing.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_retrieval.py tests/test_knowledge_v2_retrieval_security.py tests/test_knowledge_v2_retrieval_tables.py
uv run --no-sync ruff check src/anlan/evaluation evals/evaluate_knowledge_v2.py tests/test_enterprise_knowledge_evaluation.py
uv run --no-sync python evals/evaluate_knowledge_v2.py --catalog evals/enterprise-eval-v2/knowledge-runner-v1/cases.json --artifacts-dir <new-local-output-root>
```

新 CLI exit0 有限样本门禁通过，exit2 完整执行但 pending/blocked，exit1 输入/输出/完整性错误；固定三例均应实际到齐，整体不预期通过。既有 E1/E2入口/结果不重生成；全库集成由父窗口执行。

## 10. D 门禁、自审与后续验收

设计自审已核对原生签名、TXT 不能生成表格的边界、K3 逐 provider 当前治理、derived locator 和 E2a 已修复的重评分/trace/依赖完整性要求。未编造新测试结果或先写实现。

D 审重点：

- [ ] 接受两个真实 TXT 链场景 + 一个独立合成结构表 IR 后半链场景的精确范围，不宣称不存在的 XLSX 解析。
- [ ] 只新增本包文件，不修改冻结旧 E2/K/工具/M2；固定可信根和版本 sidecar 边界不放宽。
- [ ] 撤回的 provider 输入侧和后续旧目录查询都实际测量；无刺激或缺原始依赖不得给安全 pass。
- [ ] 原始观测→逐例重评分→统一报告与完整 trace payload/请求/版本校验，不退回只拼预制分数。

实施后验收：实际三例原生执行与运行产物、逐项 RED/GREEN、无未解决 Critical/Important 的独立审查、旧 E1/E2兼容与冻结 hash、Ruff 和只读隔离证据齐全，才声明本增量完成。语义、人类审核、真实 embedding/企业效果与其他未测安全项仍明确待验。

回滚只移除本包新增知识评测模块/CLI/测试/输入和独占运行目录；保留审计报告。旧 E1/E2 与 K 接口无需撤销，不回滚 ACL/withdrawal 生产记录（本包也不接生产）。禁止整体 reset/clean/restore 或删除共享报告目录。

**停止点：本文件待父窗口独立 D 审；明确触发后实施。本轮只写设计。**
