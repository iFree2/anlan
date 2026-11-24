# K3a 本地受治理结构证据检索：详细设计与测试计划

> **For agentic workers:** 只提交 D 设计门禁，未经主窗口明确触发不得编码或运行不存在的测试。实施使用 test-driven-development、verification-before-completion。共享工作树，不新建窗口/分支，不 stage/commit，不回退并发修改。

**Goal:** 在 K1/K2a 合成合同上闭环内存结构证据检索的 search/get_clause/query_table 三个只读 Python 接口，确保候选、扩展与输出始终受当前独立权威治理，缺证和预算不足保持可观察。

**Architecture:** 冻结文档目录保存完整已验证 IR 和内容摘要，内存内容投影独立解析块；先经 K1 当前治理筛选，再把授权检索文本送入可替换的本地 BM25/向量候选协议，使用 RRF 融合。所有证据从可信目录重新取原文并核对投影，父子/依赖递归展开前重检，序列化前再重检；服务仅返回证据，不生成安全判断。

**Tech Stack:** Python3.13、Pydantic v2、asyncio、标准库 math/re/decimal/hashlib/json、pytest/Ruff；无新增平台、包、模型或 SQL。

日期：2026-11-16。状态：**D 待审，尚未实现**。依据统一蓝图、总计划、knowledge-report.md、knowledge-ingest-design.md/report.md 及当前 K1/K2a 源码。使用 writing-plans 方法细化；主窗口指定本路径优先于技能默认计划路径。

## 1. 范围选择与现有合同边界

选择内存实现而非接入 OpenSearch/PG，也不修改现有512维BGE基线。BM25使用明确分词版本的本地算法；向量只定义替换协议并提供确定性离线排名替身，后续真实embedding适配和检索质量对照需另包验收。RRF只融合排名，不将score当正确概率。

现有K1没有法规文号/条款编号专用字段，编号精确检索在本包指**显式 logical_document_id/document_version_id/generation/block_id 的精确匹配**；手工结构夹具可使用4.1等block_id，不从正文猜测条款号，不声称已完成法规编号解析。

现有K1权限粒度是整文档、依赖仅限同一IR内有效block_id；本包不新增跨文档引用或伪装块级ACL。父子权限验收是每个节点展开时重新读取其所属文档当前权威输入，覆盖中途收权/撤回；跨文档独立权限扩展需后续版本合同。完整有效IR不允许悬空依赖，投影缺块、读取失败和预算不足才产生本包的dependency_incomplete。complete仅表示已声明结构依赖的组装完整，不证明自然语言主张语义完整或安全。

表格K1只有整体locator及逻辑rows，无逐单元格地图。本包query_table只对**XLSX定位且矩形范围与多级表头+数据行尺寸完全匹配**的表生成物理单元格定位；不对DOCX/PDF表格编造Excel地址，其他格式表格请求返回unknown/physical_cell_location_unavailable。合并区域/公式/跨页表定位不在本包。

三类入口只在新包内实现，**不接T1 Registry/Executor、旧query_knowledge、HTTP/CLI、模型工具目录**。后续装配由主窗口另审，不改旧工具枚举或返回合同。

## 2. 所有权与文件职责

| 新文件/目录 | 职责 |
| --- | --- |
| src/anlan/knowledge/retrieval/__init__.py | 包边界说明 |
| retrieval/contracts.py | 只读参数、可信请求上下文、证据/缺证/审计版本合同 |
| retrieval/catalog.py | 冻结InMemoryCatalog、EvidenceKey、完整IR哈希及重复拒绝 |
| retrieval/providers.py | GovernanceSource、BlockResolver、RankProvider协议及内存投影、离线替身 |
| retrieval/ranking.py | 版本化本地BM25、分词、RRF与排名返回校验 |
| retrieval/service.py | 三接口编排、前置过滤/重检/扩展/预算/错误分类 |
| retrieval/tables.py | 表格尺寸/单元格范围校验、受限Decimal筛选 |
| tests/test_knowledge_v2_retrieval.py | 排名、结构扩展、预算及三接口 |
| tests/test_knowledge_v2_retrieval_security.py | 多租户/当前权威/回滚/篡改/父子/迟到/注入 |
| examples/synthetic/knowledge-v2/retrieval/ | 明确合成结构表/场景清单，仅离线 |
| docs/phases/engineering-20261116/knowledge-retrieval-design.md | 本设计；实施报告路径待主窗口触发时明确 |

不修改K1/K2a、旧知识模块、SQL、T1核心、评测包或总文档。新增v2证据合同全部放retrieval/contracts.py，不扩大旧KnowledgeCitation。内存发布/ACL夹具只能测试宿主输入，不产生真实审核或发布记录。

## 3. 精确接口与可信输入

以下为设计签名，不是已提供API：

```python
class KnowledgeRetrievalService:
    def __init__(self, catalog: InMemoryCatalog, governance: GovernanceSource,
                 resolver: BlockResolver, vector: RankProvider | None, clock: Clock): ...
    async def search(self, request: TrustedRetrievalRequest,
                     params: SearchParams) -> EvidencePacket: ...
    async def get_clause(self, request: TrustedRetrievalRequest,
                         params: ClauseParams) -> EvidencePacket: ...
    async def query_table(self, request: TrustedRetrievalRequest,
                          params: TableParams) -> EvidencePacket: ...
```

三个方法均只读。TrustedRetrievalRequest由宿主构造：request_id（严格字符串1..128）、tenant_id、user_id、effective_at（业务时点）、scope（完整精确适用标签）。请求开始时服务用clock.utc_now()记录requested_at，clock.monotonic()计算截止期；身份/时点/适用范围禁止出现在模型可填Params中（extra=forbid）。请求ID不由provider覆盖。

每次新治理检查以clock.utc_now()产生checked_at，构造K1 AccessContext；不把requested_at或历史effective_at当最新授权读取时点。返回EvidencePacket只写宿主元数据，provider只可给key和排名。

所有合同继承K1 Contract，严格冻结、tuple集合、版本Literal；标识沿用Text，问题字符串strip后1..500，参数严格int，bool不得冒充数字。身份权限不可由正文、查询或向量provider改写。

### 3.1 三种模型可填参数

- ClauseSelector：logical_document_id、document_version_id、generation>=1、block_id，均精确匹配，tenant隐含当前可信请求；不接受任意路径/URL。
- SearchParams：question（1..500）、exact: ClauseSelector|None、mode: lexical/hybrid（默认lexical）、top_k（1..5，默认3）。exact有值时仅查该编号，仍重检，不调用排名器；exact无值才执行词法/混合检索。
- ClauseParams：selector: ClauseSelector。没有跳过权限/依赖的参数，必要父节点和显式依赖始终要求补齐。
- CellFilter：column（0-based严格int，0..99）、op: eq/gt/ge/lt/le、value（Text，1..64）、expected_unit: str|None。eq按原始字符串完全相等；其余比较需显式expected_unit与table.units[column]逐字相等。
- TableParams：selector、filters（tuple，最多8项，AND）、row_limit（1..20，默认10）。无需过滤可空tuple，但仍受行扫描/输出上限。没有SQL、脚本、正则、自由字段路径或自动单位转换。

### 3.2 目录与投影

EvidenceKey包含tenant_id/logical_document_id/document_version_id/generation/block_id，严格等值，作为所有候选和引用的唯一主键。

InMemoryCatalog构造时接收tuple[DocumentIR,...]并完整验证；拒绝重复(tenant,logical,version,generation)，保存目录revision（对排序后的完整IR摘要序列求SHA256）、每文档ir_sha256和块映射。上限32文档、8192总块、完整IR JSON总计8MiB；超限构造失败，无静默部分目录。只在初始化构建；无持久化/热更新API。每请求固定目录revision，服务实例不保存会串请求的身份/授权状态。

BlockResolver用于模拟可重建内容投影，async resolve(key)->Block|None；默认InMemoryBlockResolver从目录建立完整投影；测试可有意移除某父块/依赖，以真实验证投影缺块。完整IR仍保留在目录以校验发布摘要，**不将这个模拟称为原文件丢失**；服务不绕过投影缺块自动从目录补出内容。返回Block必须与目录该key的完整块逐字段相等，错误源文/locator/表格/ID/顺序均data_error并排除。None为projection_missing。未知key不得进入resolver。

### 3.3 当前权威源协议

```python
class GovernanceSource(Protocol):
    async def read_current(self, *, tenant_id: str, logical_document_id: str,
                           checked_at: datetime) -> GovernanceRead: ...
```

GovernanceRead版本knowledge.governance-read.v1，包含authority:AuthoritySnapshot|None和manifest:ReleaseManifest|None。宿主保证一次原子、最新读取；本包测试提供每次调用可变的明确内存账本替身，记录调用次数。禁止从回滚目录、IR或旧证据缓存构造authority。无默认全允许源，缺记录直接K1拒绝。

治理检查每次调用K1 evaluate_access(doc,ctx,authority,manifest)，实际重新计算ir摘要。初次通过时把本请求选择的release fingerprint（完整manifest的规范JSON SHA256）记入请求局部状态；后续检查若active manifest fingerprint变动，当前文档结果丢弃，issue=release_changed，不在同请求偷偷切代次。ACL/withdrawal revision可以变化，必须用当前新值重新判定；收权/撤回后即使旧manifest或目录回滚也不能复活。

当前读取新鲜性/发布身份认证最终依赖宿主；checked_at不能证明后端没有重标旧记录，不声称本包实现生产认证或线性一致存储。输出前最后一次本地检查之后的撤回竞态无法被普通离线函数彻底消除；后续消费者必须在缓存命中/模型重排/使用前重新执行治理，证据包不作为授权凭据。

## 4. 候选检索与RRF

1. 先按可信tenant筛目录，其他tenant的文档不调用权威源、不调用provider、不返回其ID/标题/计数。
2. 对当前tenant每个候选文档调用最新权威源并执行K1。缺scope/范围不符、未知记录、未审核发布、过期、撤回、版本/摘要不匹配均不能进入候选语料。面向调用者仅返回无泄漏的聚合缺证码，拒绝文档ID/原文只在宿主内部保留最小审计（不记录拒绝正文）。
3. 仅将授权块的(key,retrieval_text)构成CandidateText交给词法/向量provider，禁止传source_text/manifest/ACL/其他tenant内容。候选语料最多256块且UTF8检索文本总计1MiB；按key稳定排序取有界前缀，超限标candidate_truncated和limited覆盖，不宣称全库已搜。exact路径不受provider语料前缀影响，但仍受总请求预算。
4. 本地BM25 tokenizer_version=cjk-bigram-asciiword-v1：按连续汉字串生成相邻双字（单字串保留单字）；ASCII字母/数字/下划线/点/斜线/连字符串作为小写token。只规范检索表示，不改原文；其他未覆盖字符不猜测，零token/零命中保留unknown。k1=1.5、b=0.75、idf=log(1+(N-df+0.5)/(df+0.5))，只返回正分候选；空库直接空列表。
5. RankProvider协议 async rank(question,candidates,limit)->tuple[RankedKey,...]，RankedKey只含EvidenceKey和finite score；vector provider_version和processor_version为固定宿主属性，不接受其返回覆盖。无真实向量默认None；mode=hybrid但缺vector时保留词法结果并标provider_unavailable/incomplete，不伪造向量分。
6. 离线向量替身按显式key排名表返回，不声称编码或语义检索；真实BGE接口/512维模型不动。可替换BM25 provider同样满足此协议，默认本地BM25。
7. 每路最多20候选；返回重复key、非授权key、错误tenant/版本/代次、NaN/Inf或超额数量均provider_contract_error，整路结果丢弃，不能静默清洗后当全部成功。相同分数按完整key稳定排序；不让provider提供来源/引用正文。
8. RRF常数k=60，score(key)=sum(1/(60+rank))，rank从1开始；同一key各路只计一次，按score降序再按key排序。取top_k主命中，再治理检查/解析原块；没有全局相似度阈值或正确概率解释。
9. **每一路RankProvider必须串行执行各自的治理与语料重建，禁止复用首轮全集或并发启动lexical/vector。** 精确顺序为：①为lexical读取当前治理，重建此次可见CandidateText及call_allowlist；②await lexical；③检查截止期，用lexical自己的call_allowlist校验返回key（未在该次allowlist出现的key才属provider_contract_error）；④重新读取当前治理，删除期间撤权/撤回/发布变化文档的lexical排名及全部累积证据；⑤在**vector调用前再次读取当前治理**，从当前仍允许且release fingerprint不变的文档重新构建vector专属CandidateText及call_allowlist，绝不复用lexical调用前缓存的语料tuple；⑥仅在vector语料非空时await vector，再按自己的allowlist校验，并在消费结果前重读治理。两路之间复用的只能是目录/IR和固定处理版本，不能是授权结论或旧CandidateText。resolver每次await返回后也遵循截止期→当前治理→消费结果的顺序。

   本请求维护单调增长的invalidated_documents集合：任一路期间收权、撤回或已选release fingerprint变化的文档立即加入，清除其排名/证据，不在本请求后续路次重新引入，即使稍后回读又允许或切回旧清单也不恢复。manifest变化统一release_changed，不切源、不切代次。若lexical期间全部文档失效，vector调用数为零，返回无正文的unknown及authorization_changed/release_changed。普通本地检查不能消除检查之后发生的外部撤回竞态，边界见第3.3节。
10. 不实施模型reranker、缓存或多轮问题改写。将来接入这些组件时仍要求在输入/输出边界重检，不因本包提供rank协议就宣称已集成。

## 5. 结构扩展与缺依赖语义

命中块的parent_id和dependencies取自审核摘要绑定的完整IR，迭代遍历传递闭包、按原order稳定输出、共享节点只记一次。**不自动补齐所有兄弟/子块**：完整父块源文本身若包含完整条款则保留；本包不从部分子块拼出“完整条款”。每个节点取出前均重新治理所属文档，再调用resolver并比较完整块。

若projection_missing、读取失败、节点/字节/时间预算不足，EvidenceItem.dependency_state=incomplete，issues列固定原因；不伪造缺失块的文字或定位。对已授权可见的依赖可列其key，对拒绝或未知权限不输出该节点ID；父子同文档若发生收权/撤回，则**整文档所有已累积证据一并删除**，不能只删除父块却保留此前已无权的子块。最后输出前逐文档再读取当前权威并重检，迟到投影/候选结果不得跳过此门。

无效IR（缺依赖、循环、重复块）在目录初始化即拒绝，不把invalid corpus包装成完整证据。投影缺块和预算截断可以返回有界且明确incomplete的已授权片段；没有片段时status=unknown或error，不能伪造empty=无风险。query_table也要满足该表块的必要结构依赖，不以筛选结果替代依赖。

## 6. 表格代码筛选与单元格定位

仅kind=table且source_format=xlsx/locator.kind=xlsx进入筛选。解析SheetLocation起止列行，范围列数必须等于每行宽度，范围行数必须等于len(headers)+len(rows)；否则unknown/physical_cell_location_unavailable，不猜测表头占用行。

CellLocation版本knowledge.table-cell.v1：sheet、cell（A1单格地址）、table_key、data_row（0-based）、column（0-based）；物理列=起始列+column，物理行=起始行+len(headers)+data_row。每个输出值必须同时附table块整体locator、原表source_text和ir摘要；值为表格结构原始字符串，不用模型生成。table单元格字符串应在table.source_text中有连续原文对应（空单元格可值为空但不作为引用quote）；不满足则data_error，不能用结构值冒充可核验源文。

数值比较仅接受ASCII `[-+]?[0-9]+(?:\.[0-9]+)?`，用Decimal比较，拒绝NaN/Inf/指数/逗号/带单位文本/空值；expected_unit与列unit不符不自动换算。无法解析的扫描行标unknown_cells，不能当不匹配而静默丢弃；整体status=incomplete。eq原字串比较不需要数值解析。

行扫描最多200行（代码执行步预算），超限停止并标table_scan_limited。匹配行超过row_limit时只输出前row_limit，标result_limited；无自动分页/cursor。只有全部范围完成且零未知/故障/截断时，空匹配才可表达“在本次明确表格范围内无匹配行”；永不推断“无风险/全部安全”。返回headers/units/footnotes原结构，不能只返回孤立数值。

## 7. 证据包、审计与错误合同

EvidencePacket schema_version=knowledge.evidence.v2；operation=search/get_clause/query_table；request_id/requested_at/effective_at、catalog_revision、processor_version=knowledge-retrieval-k3a/1、tokenizer_version/provider版本、status=evidence_found/unknown/incomplete/error、coverage=exact_selection/limited_candidates/table_range、items、table_rows、issues、audit、finished_at。

EvidenceItem包含EvidenceKey、data_origin=SYNTHETIC、reference_kind=synthetic_reference、title/source_uri、原始完整source_text、locator、source_sha256、ir_sha256、generation、Lineage、最后治理checked_at、release_fingerprint、ACL/withdrawal revision、dependency_state=complete/incomplete、required_keys（仅可见节点）。不输出retrieval_text作为quote；provider score仅可作排名诊断，不作风险概率。证据包含来源定位/hash不等于外部真实性、法律效力或语义支持证明。

IssueCode固定全集：no_authorized_evidence、applicability_unknown、not_found、projection_missing、dependency_incomplete、provider_unavailable、provider_contract_error、data_error、release_changed、authorization_changed、candidate_truncated、node_limited、byte_limited、deadline_exceeded、authority_budget_exhausted、table_scan_limited、result_limited、unknown_cell_value、physical_cell_location_unavailable。没有未经验证的free-text“已安全/批准”。

EvidenceIssue字段仅code:IssueCode及related_key:EvidenceKey|None；拒绝/未知权限必须related_key=None。Packet合同校验：evidence_found必须至少有一个item或row且无不完整/故障issue；complete的item所需required_keys必须全在同包items里；unknown/error不得带未最终重检的内容。数据来自宿主重新组装，provider不能构造EvidencePacket覆盖这些字段。

外层status规则：无任一有效item/row且权限或定位/编号不明→unknown；有片段但依赖/路由/扫描/预算不完整→incomplete；provider/投影合同故障且无可用片段→error；有内容且声明结构覆盖完整→evidence_found。即使evidence_found也不包含安全结论。scope为空时在候选前返回unknown/applicability_unknown，向量/解析调用数为零；scope不符仅给no_authorized_evidence，避免泄漏未授权规则。

审计为返回值中的有界宿主元数据，不写外部日志：request_id、stage、已授权key（拒绝时无key）、decision_code、provider版本、耗时、governance revision、预算消耗。无原文、query全文、许可正文、密钥或DSN。最多128条，计数溢出只记固定audit_truncated标记（单独diagnostics flag，不伪装业务完整）。不通过工具发送消息。

参数/目录合同错误为ValidationError（不直接渲染input）；provider/权威源/投影普通异常映射固定码且不复制异常文本。asyncio.CancelledError传播，不转换为unknown；超时明确deadline_exceeded，取消协作任务并丢弃迟到结果。不自动重试。

## 8. 固定预算与并发约束

每请求硬上限：5秒墙钟（monotonic）、32个组装节点、64KiB完整EvidencePacket UTF8 JSON、128次权威读取、32次projection读取、每路20候选、最多两路排名provider调用、200表行扫描。查询top_k<=5、row_limit<=20；不得通过模型参数扩大。以上只属于新独立K3a，不改T1固定链或模型预算账本。

每个异步边界使用剩余时间wait_for；provider为可信本地协作代码，不声称能隔离阻塞事件循环或恶意Python。每次本地循环检查monotonic和预算；超限无自动重试。不截断原文字符串冒充完整quote：以整EvidenceItem/整表行为单位装入，超64KiB标byte_limited；metadata保底可序列化时保留状态/issue，无内容也不返回pass。审计单条预算256bytes，超长key仅记规范key摘要；最终序列化超限先按整条审计削减并置audit_truncated，再按整item/row削减且重算dependency_state/status。最小包仅保留有界request_id/时间/版本/固定issues，仍须实际测量UTF8字节，不能用字符数代替。

权威读取预算必须预留输出前重检名额；若无法完成最终重检，丢弃未最终复核文档内容，返回unknown/incomplete/authority_budget_exhausted。不能因为读取预算耗尽而复用旧allow。5秒到期后禁止启动新任务；provider忽略取消后返回的迟到结果也不发布。

服务构造不写全局身份，所有release fingerprint、预算、临时排名和审计均请求局部；两个并发请求不同tenant/scope不得交叉污染。无检索缓存；目录回滚不回滚authority源。

## 9. TDD 任务与实际观察要求（D通过后）

### A. 证据/参数/目录合同

- [ ] 新test文件先写版本/extra/严格int/禁止身份字段、不可变、重复目录ID、无效IR拒绝测试；缺新包用明确assert失败，不importorskip。运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_retrieval.py -k contracts` 观察RED后实现最小合同。
- [ ] 覆盖完整源文/locator/hash/代次/Lineage/时点必须存在；未知不能构造成完整业务结论。构造目录摘要需对实际IR算hash，不只断言长度。

### B. 编号、BM25和RRF

- [ ] 用K2a parse_txt对实际合成bytes派生IR，默认不发布应unknown；合法合成manifest作为测试宿主夹具显式创建并标非真人审核。
- [ ] 编号精确命中、错误版本/代次/编号不命中、零token/零结果unknown、BM25确定排序、两路重复key融合只计一次；先写测试再跑RED，再实现。
- [ ] 用精确分数断言：keyA两路rank1/2→1/61+1/62，keyB单路rank1→1/61，A优先；非法重复/越权key/NaN/超额整路拒绝。向量None不伪造结果。
- [ ] 运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_retrieval.py -k 'exact or bm25 or rrf'` 逐组记录RED/GREEN。

### C. 当前权威与扩展安全

- [ ] spy providers接收的所有CandidateText只含同tenant且初次治理通过块；跨租户、越权、过期、未审核/未发布、缺ACL/撤回、scope缺失在调用provider前被阻断。
- [ ] authority替身第N次读取切换收权/整文撤回/版本撤回；主命中后父节点展开前、resolver await之后、最终输出前分别切换，结果不能残留同文档子块。
- [ ] **逐路语料隔离RED/GREEN（D审查important）**：async lexical替身收到授权文档A/B后，在返回前把A在独立当前账本中设为withdrawn或从allowed_users移除；vector spy记录每次实际接收的CandidateText。断言vector收到的keys和retrieval_text均不含A，只可包含仍授权B；若只有A，则vector调用数必须为零。先运行该安全用例观察旧“最初筛一次后两路复用语料”实现的真实RED，再改为每路前读取/重建，运行GREEN；禁止只检查最终packet不含A来替代输入侧断言。
- [ ] 同一逐路用例把A的manifest fingerprint改成另一代次，确认vector不收到A、packet.issue为release_changed且不读取替代IR切源；再把manifest恢复旧值，当前请求的invalidated_documents仍不得复活A。provider key合法性按各次call_allowlist验证，不能把调用期间合法候选被撤回误判为provider伪造key。
- [ ] 合法旧IR/manifest回滚配最新撤回账本仍拒绝。manifest切代次、IR原文/retrieval/locator/table/lineage被篡改但保留source hash时release mismatch；篡改投影Block则data_error；伪造provider源元数据字段extra拒绝。
- [ ] 默认完整投影的父/依赖闭包、共享依赖去重、投影删掉父块→incomplete；IR悬空/循环在目录处拒绝。父子同文档ACL粒度明确，不伪造跨文档测试。
- [ ] 并发两tenant请求和正文注入不改变身份/时点/已选发布。运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_retrieval_security.py`，真实观察RED/GREEN。

### D. 表格与预算

- [ ] 手工构造明确SYNTHETIC XLSX结构IR，范围A1:B4含两级header+两数据行；column1/data_row0的物理地址应B3。尺寸不符、PDF表格、原文找不到单元格值均不能伪造定位。
- [ ] Decimal边界10/10.0/9.9、负数、eq字符串、单位不符、NaN/空值/指数、无匹配/扫描不完整分别验证；返回headers/units/footnotes与cell地址。
- [ ] 节点32/33、200/201扫描行、64KiB边界、provider20/21、authority预算预留、投影读取预算、clock截止前/后、超时/取消/迟到结果分别RED/GREEN；不使用真实sleep超60秒，用可控时钟/async事件与短超时。

可执行预期断言示意（接口均在本文定义，尚未实现）：

```python
packet = await service.get_clause(request, ClauseParams(selector=selector))
assert packet.items[0].source_text == source_block.source_text
assert packet.items[0].ir_sha256 == document.content_digest()
assert packet.items[0].locator == source_block.locator
# 在投影删除必要父块的另一个场景中：
assert packet.status == 'incomplete'
assert 'dependency_incomplete' in tuple(issue.code for issue in packet.issues)
```

## 10. 场景验收清单

| 场景 | 必须观察 |
| --- | --- |
| K2a合成TXT→显式合成发布输入→search/get | 真实bytes/hash/行号可回溯，不把AI标签当人工金标 |
| scope缺失/错tenant/收权/过期/未发布 | provider看不到拒绝正文；无权限/来源信息泄漏 |
| 候选后撤回/父扩展时收权/最终检查前切清单 | 所有同文档旧证据移除，明确unknown/incomplete |
| lexical await期间撤回/收权后再进vector | vector spy实际语料不含撤权文档；全部失效则零调用，不能仅删最终输出 |
| 旧代次目录回滚 | 最新withdrawal/ACL仍拒绝；无历史时点绕过 |
| 子命中+父依赖缺投影/预算不足 | incomplete，无伪父文字或完整条款宣称 |
| 源IR篡改/投影篡改/恶意rank key | K1摘要或逐块比对阻断，不成为有效引用 |
| 表格筛选与单元格 | 代码Decimal比较、真实合成坐标B3、单位/脚注保留 |
| 无匹配/未知数值/没扫完 | 三者分别呈现，空不等于安全 |
| provider/authority超时/取消/异常 | 分类、取消传播、无重试、迟到结果丢弃 |
| 预算与并发 | 固定上限、最终重检不绕过、请求不串tenant/目录 |

## 11. 验证命令、交接和回滚

D通过且明确触发后才执行；以下没有实际结果或预填通过数：

```powershell
uv run --no-sync pytest -q tests/test_knowledge_v2_retrieval.py tests/test_knowledge_v2_retrieval_security.py
uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py tests/test_knowledge_v2_retrieval.py tests/test_knowledge_v2_retrieval_security.py
uv run --no-sync pytest -q -rs tests/test_knowledge.py tests/test_knowledge_tool_loop.py tests/test_knowledge_cli.py tests/test_knowledge_evaluation.py
uv run --no-sync ruff check src/anlan/knowledge/retrieval tests/test_knowledge_v2_retrieval.py tests/test_knowledge_v2_retrieval_security.py
```

当前K1+K2a已有130 passed作为定向基线；PG测试仍需显式DSN，缺环境不计通过、不改skip；全量集成由主窗口负责。报告逐组真实RED/GREEN、独立审查、文件及未验项，工程机制与真实检索效果/领域语义支持分别交接。

回滚仅移除新retrieval包、新测试和自有合成夹具/报告；未装配T1或旧工具，无SQL迁移。不得reset/clean共享工作树或回滚权威ACL/撤回账本。无模型生成、真实企业语料、平台接入、生产部署或自动批准。

## 12. 设计自审与D停止点

- [x] 三接口、授权读取/发布绑定、候选provider、投影、表定位、预算与错误均有精确边界及对应测试任务。
- [x] K1缺条款字段/块ACL/跨文档引用/逐cell地图的限制显式，不编造已有能力。
- [x] 缺依赖由真实投影缺项/预算不足表达；有效IR不允许悬空引用。撤回后整文档删除，末次检查预算不可绕过。
- [x] 只有合成已见夹具；向量替身不等于BGE或真实检索质量，未伪人工金标。
- [x] 无实现、无执行预期测试；只新增本文，不改旧模块/核心/历史文档。
- [ ] D主窗口独立审查并触发实现。当前停在此处。

### D 初审修订记录（仍未批准实现）

主窗口指出1项Important：lexical await期间撤回后，vector不能继续接收首轮已授权但现已撤权的文本。已将第4节步骤9落实为每路独立读取治理、重建CandidateText、每次返回后重检和单调失效文档集合，并在第9节C及第10节加入明确vector spy输入侧RED/GREEN验收；已选release fingerprint变化仍拒绝，不切源。此处仅修订设计，最终D仍待主窗口完成其余审查，未新增实现或测试文件。

### D 最终条件通过及实施触发追加

主窗口已明确：逐provider前重读治理/重建语料后，补两项约束即可TDD实施，无须再次等待。CellLocation必须标记derived_from_reviewed_ir，表示从审核矩形IR推导，未重新读取XLSX验证；source_text包含单元格字符串不证明真实物理地址。64KiB输出裁剪按完整packet UTF8字节测量，表证据与rows联动，不能留无源table/headers/units/footnotes的孤立数值；必要依赖被裁必须incomplete。执行报告独占knowledge-retrieval-report.md。以下实施以这些最终约束为准；原设计记录保留。
