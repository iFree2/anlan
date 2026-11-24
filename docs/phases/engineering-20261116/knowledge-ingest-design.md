# K2a 本地 UTF-8 TXT 候选摄取详细设计与实施测试计划

> **For agentic workers:** 本文仅提交 D 设计门禁审查，尚未批准实现；主窗口明确触发后，使用 test-driven-development 和 verification-before-completion 逐项实施。继续当前共享工作树，不创建分支/窗口，不 stage/commit。不得把本文的预期测试结果当成已运行证据。

**Goal:** 将一份受限、明确 SYNTHETIC 的 UTF-8 TXT 原始 bytes 转为 K1 DocumentIR 和独立候选来源登记，完整保留原字节、行位置与原文，始终保持未发布。

**Architecture:** 纯函数入口只接收宿主已经取得的 bytes 与受限逻辑文件名，不读取任意文件路径、不联网。冻结候选登记与摄取元数据严格校验后进行大小/编码/行数/内容检查；解析草稿包含原字节、IR 和候选登记。K1 治理仍使用独立权威输入，不修改现有授权/发布规则。

**Tech Stack:** Python 3.13 标准库 hashlib/json/re/urllib.parse、现有 Pydantic v2 与 pytest/Ruff；不增加依赖、模型、平台或 SQL。

日期：2026-11-16。范围：K2a 最小本地纯解析增量，**状态 D 待主窗口审查，零实现**。依据统一蓝图、总计划、K1 报告及主窗口 `public-corpus-sources.md`。ModelScope 信息仅沿用该登记作为设计输入，本窗口未重新查证、下载或复制真实语料。

## 1. 方案选择与门禁

方案一：直接接收任意本地路径并打开文件，需要跨平台根目录校验、符号链接/reparse point 与打开时竞态处理；本包不选择。

方案二（选择）：接收有上限的 bytes，逻辑文件名只用于格式检查，不把它当路径。无本包文件系统读取接口，因此路径逃逸在入口直接拒绝；测试夹具由测试自身从确定路径取得 bytes。业务入口/CLI 的受限文件读取适配属于独立后续包，不能据本包宣称支持任意本地路径导入。

方案三：连接 ModelScope SDK 或网页批量下载并自动识别格式，会引入网络、脚本信任、许可与资源问题，超出当前授权。

D 门禁审查重点：认可 bytes 入口的精确范围、空白行保留规则、候选许可状态和 K1 衔接。若主窗口要求本轮提供文件路径 API，需先补 Windows 安全打开及竞态设计再执行，不能简单 resolve 后 open 冒充根目录隔离。

## 2. 所有权与文件职责

| 文件 | 本包动作与职责 |
| --- | --- |
| `src/anlan/knowledge/parsing/__init__.py` | 新增，说明仅支持受限合成 TXT 候选摄取 |
| `src/anlan/knowledge/parsing/contracts.py` | 新增，SourceCandidate、LicenseEvidence、TxtIngestMetadata、TxtIngestDraft、TxtIngestError |
| `src/anlan/knowledge/parsing/text.py` | 新增，parse_txt 及固定资源界限、编码/行定位转换 |
| `src/anlan/knowledge/parsing/_text_source.py` | 新增，固定资源界限、受限文件名与原始字节拆行的纯辅助；由 parser 和草稿自校验共同调用，避免循环导入 |
| `tests/test_knowledge_v2_parsing.py` | 新增，合同、拒绝路径、精确字节/行与未发布回归 |
| `examples/synthetic/knowledge-v2/ingest/` | 新增合成 TXT 和候选元数据 JSON；不存未知授权全文 |
| `examples/synthetic/knowledge-v2/README.md` | 实现通过后仅追加 TXT 边界及命令 |
| `docs/phases/engineering-20261116/knowledge-ingest-design.md` | 本文，唯一当前新增文件 |

不改旧 knowledge contracts/store/tool/embeddings，不改 K1 合同及治理实现，不改 SQL、工作流、CLI、status/roadmap/架构/能力/学习总文档、公开来源登记。实施报告路径须在主窗口触发时确认所有权；默认向本文追加执行证据，保留当前设计，不覆盖 K1 报告。不得回退并发改动。

## 3. 精确接口与合同

计划公共入口（签名设计，未实现）：

```python
def parse_txt(
    raw: bytes,
    *,
    filename: str,
    metadata: TxtIngestMetadata,
    candidate: SourceCandidate,
) -> TxtIngestDraft: ...
```

入口仅接受 `type(raw) is bytes`，不接受 str、Path、bytearray、memoryview、文件对象或自动解码输入。filename 必须 str，长度 1..120；不得包含 `/`、反斜杠、冒号、NUL 或 ASCII 控制字符，不得以空格/点结束，不得是 `.`/`..`/`.txt`；必须有非空 stem，大小写不敏感后缀 `.txt`。拒绝绝对路径、驱动器相对路径、UNC、目录穿越、URL 和 NTFS ADS。文件名是显示用逻辑名，绝不 open/resolve 或拼接为宿主路径；不承担文件系统安全读取器职责。

所有 Pydantic 合同沿用 K1 `Contract`（extra=forbid、strict=True、frozen=True），集合使用 tuple，不用可变 list/dict 暴露状态。

### 3.1 候选来源登记

`SourceCandidate` 字段：

| 字段 | 类型/语义 |
| --- | --- |
| schema_version | Literal `knowledge.source-candidate.v1`，显式必填 |
| candidate_id | K1 Text，宿主本地登记标识，不是来源认证 |
| data_origin | Literal SYNTHETIC；本轮拒绝 PUBLIC/ENTERPRISE，避免修改 K1 SYNTHETIC 边界 |
| source_url | K1 Text，独立登记来源地址；仅接受 `https` 或 `synthetic`，验证 scheme/host（synthetic 亦须非空 netloc），拒绝 userinfo/控制字符；不发请求、不执行脚本 |
| publisher | K1 Text 或 None，None 表示发布方未确认，不猜测 |
| upstream_revision | K1 Text 或 None；None 表示未知，不能填 latest 假装固定版本 |
| retrieved_at | AwareDatetime 或 None；表示宿主登记的获取时点，不由 parser 捏造 |
| license_id | K1 Text 或 None；可记录上游声明，但不等于再分发授权 |
| license_evidence | LicenseEvidence 或 None；缺失仍可登记为 candidate，不能升级 |
| review_state | Literal candidate/needs_review/rejected，显式必填；本轮没有 approved/published |
| expected_source_sha256 | K1 Digest 或 None；有值时必须与实际 raw hash 相等 |

`LicenseEvidence` 字段：evidence_url（与 source_url 同一 URL 语法校验）、observed_at（AwareDatetime）、statement（K1 Text，宿主保留的许可声明摘要）、evidence_sha256（K1 Digest 或 None，未保存许可原件时不可伪填）。本包只校验结构，不验证许可内容、网页真实性或再分发权；无网络访问。合成元数据使用 synthetic:// 或 https://example.invalid，清晰标记 SYNTHETIC，publisher/revision/license 声明都不冒充真实来源。

`rejected` 可保存为登记对象，但 parse_txt 必须以 candidate_rejected 拒绝摄取；candidate/needs_review 均只能产出未审核草稿。重复 candidate_id 的持久化唯一性不由纯函数实现。

### 3.2 摄取元数据

`TxtIngestMetadata`：tenant_id、logical_document_id、document_version_id、title 为 K1 Text，generation 为 strict int >= 1；不接受模型身份、权限、审核人、published、allowed_users 等额外字段。以上均由可信宿主提供，本包不执行身份认证、不根据文本推断租户。

### 3.3 草稿结果

`TxtIngestDraft`：schema_version Literal `knowledge.txt-draft.v1`；raw_bytes: bytes；filename: str（已按入口规则校验）；candidate: SourceCandidate；document: DocumentIR；omitted_blank_lines: tuple[int, ...]；review_state Literal needs_review；published Literal False。

raw_bytes 在内存保留，写入后续原文件仓库未实现。返回冻结模型，不提供自动发布、索引写入、网络下载、磁盘写入接口。草稿自校验重算 raw_bytes hash 等于 document.source_sha256，并要求 candidate.expected_source_sha256 若有值与之相等；防止直接构造矛盾草稿。同时按第4节规则验证 document 的 source_format=text、每块源文/检索文/行号与 raw_bytes 对应物理行完全一致、omitted_blank_lines 恰好是全部空白行，不允许直接构造带错误文本或定位的草稿。一致性检查与 parser 共同调用 parsing/_text_source.py 的纯拆行辅助函数，避免循环导入；不调用发布或治理接口。source_url 只存在于独立登记，不自动变成可信原文来源。

## 4. TXT 字节、行与 IR 映射规则

1. 固定 MAX_SOURCE_BYTES=262144（256 KiB），MAX_PHYSICAL_LINES=4096；不接受调用者放宽的 limits 参数。读取已经发生在宿主，但解析前立即用 len(raw) 拒绝超限，避免解码/拆分超限资源。
2. 空 bytes 拒绝；严格 UTF-8 解码（errors=strict），不自动探测 GBK、不 replace。本轮拒绝 UTF-8 BOM，明确错误 unsupported_bom；原字节包含 BOM 时绝不悄悄删后声称原文不变。
3. 拒绝 NUL、ASCII 控制字符 U+0001..U+0008/U+000B/U+000C/U+000E..U+001F/U+007F；允许 TAB、LF、CR。不执行宏、脚本、模板或正文中的指令。
4. 只把 CRLF、LF、CR 视为物理行结束，使用保留结束符的拆行规则；不得用会把 Unicode NEL/LS/PS 当成新行的通用 splitlines。末尾换行不制造不存在的末行；非换行结尾的末行正常保留。
5. 对每行仅用 `line.strip()` 判断是否为空白行；非空白行的完整字符序列（含前后空白和真实 CR/LF 终止符）原封不动保存为 block.source_text，retrieval_text 与 source_text 相等。不得做 strip/换行归一/Unicode 规范化/数值单位替换/标题增强。
6. 空白行因 K1 Block.source_text 必须含非空白字符而不构造成 Block，其 1-based 原始行号记录在 omitted_blank_lines，原 bytes 仍完整保留。全空白输入拒绝 empty_text。Unicode NEL/LS/PS 若存在作为原文字符保留，不引入行定位；它们不是本包换行符。
7. 每个非空白物理行产出 paragraph Block；order 使用已输出块的 0-based 连续序号；block_id 为 `line-{physical_line_number}-{sha256(line.encode('utf-8'))[:16]}`。parent_id=None、dependencies=()、table=None，不伪造章节/表格/条款语义。
8. TextLocation(kind=text,line_start=n,line_end=n)，n 是原字节解码后的实际物理行号，空白行不压缩定位。每块等于原始物理行，无跨行拼接，不把检索增强文本当源文。
9. DocumentIR.schema_version=knowledge.document.v2，data_origin=SYNTHETIC，source_format=text；source_sha256=sha256(raw).hexdigest()；source_uri=`synthetic://knowledge-v2/txt/{source_sha256}`，用于定位当前草稿资产，不暴露宿主绝对路径，不声称该 URI 已有对象存储。
10. Lineage.parser=anlan.restricted_utf8_txt，parser_version=1；config_sha256 对固定配置（最大字节/行数、UTF-8 strict、拒绝 BOM、换行保留、空白行策略）使用与 K1 一致的排序紧凑 UTF-8 JSON SHA256；transformations=()，quality=unverified。行提取是确定性解析，不意味着真人核验。
11. 内容摘要继续使用 K1 DocumentIR.content_digest()；本包不生成 ReleaseManifest。治理验证必须以 manifest=None 拒绝 unpublished；即便来源登记存在许可材料也不改变该结论。

## 5. 错误合同与输出控制

`TxtIngestError(ValueError)` 暴露只读 code（下表 Literal），str(error) 仅输出固定 code，不包含原文、URL、磁盘路径、异常解码片段或凭据。Pydantic 对直接构造合同的 ValidationError 不经本包写日志；本包无日志/CLI/HTTP。未来外部入口必须先做错误脱敏，不能直接展示 ValidationError 的 input。

错误顺序固定：invalid_input → invalid_filename → unsupported_format → oversized_source → empty_source → candidate_rejected → source_hash_mismatch → unsupported_bom → invalid_utf8 → unsupported_control → too_many_lines → empty_text。合法合同的其余 IR 构造若失败不能降级成成功。

invalid_input 为 raw/filename 的运行时类型错误；invalid_filename 为路径及名字形状；unsupported_format 为合法无路径名的非 TXT 后缀。合同不合法直接 ValidationError（创建 metadata/candidate/draft 时）。本包无重试、fallback、跳过文件或返回部分成功。

## 6. TDD 实施步骤（主窗口触发后执行）

### A. 严格来源/摄取合同

- [ ] 在 test_knowledge_v2_parsing.py 写合同测试，先断言 parsing 包存在，使缺包成为清楚的 assertion failure，不使用 importorskip。运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k contracts`，观察 RED 后再新增 contracts.py。
- [ ] 验证 schema 版本、额外字段、strict generation、冻结、naive datetime 拒绝；source_url/evidence_url 非许可 scheme、userinfo、控制字符拒绝；candidate 许可/revision 缺失可以候选登记；published/approved 字段或状态拒绝。
- [ ] 实现最小合同，重复同命令观察 GREEN。用真实模型校验，禁止 mock 候选状态或 ValidationError。

### B. 精确字节与行转换

先写如下行为测试（导入路径为 anlan.knowledge.parsing.text；metadata/candidate 来自合成 fixture）：

```python
raw = 'SYNTHETIC 首行  \r\n\r\n\t第二行不得改写数值 10。\n末行'.encode('utf-8')
draft = parse_txt(raw, filename='sample.txt', metadata=metadata, candidate=candidate)
assert draft.raw_bytes == raw
assert draft.document.source_sha256 == hashlib.sha256(raw).hexdigest()
assert [b.source_text for b in draft.document.blocks] == [
    'SYNTHETIC 首行  \r\n', '\t第二行不得改写数值 10。\n', '末行']
assert [b.locator.line_start for b in draft.document.blocks] == [1, 3, 4]
assert draft.omitted_blank_lines == (2,)
assert all(b.source_text == b.retrieval_text for b in draft.document.blocks)
```

- [ ] 运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k exact`，实际观察因 parse_txt 未实现而 RED；然后实现最小 parser 并重复到 GREEN。
- [ ] 增加 LF/CR/CRLF、有无末尾换行、连续空白行、首尾空格/TAB、中文/emoji/组合字符、NEL/LS/PS 保留的参数化精确断言；重复输入 block IDs/IR digest/config digest 确定性相等；改变换行的 raw hash 必须改变。
- [ ] 草稿直接构造时的 raw/hash 矛盾、source_text/retrieval_text 篡改、错误 line_start/line_end、伪造空白行清单或非text source_format 必须拒绝。测试不得只断言 digest 长度；必须与 hashlib 对实际 bytes 的结果比较。

### C. 拒绝边界与资源上限

- [ ] 测试参数集见第 7 节，先运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k rejects` 记录实际 RED，再实现对应拒绝分支到 GREEN。每组新增分支均有对应失败证据。
- [ ] 字节上限取恰好 262144 合法内容、262145 拒绝；物理行上限取 4096 合法非空行、4097 拒绝。内容必须确实满足其他限制，避免被更早分支遮蔽。
- [ ] 检查固定错误码及 str(error) 不包含 sentinel 原文/路径/URL。用 bytes API 直接测试，无真实网络、模型或 PG。

### D. K1 衔接与完整定向复验

- [ ] 先新增“候选摄取不能发布”测试：草稿 review_state=needs_review、published=False；K1 evaluate_access 传合法 authority/context 但 manifest=None 必须返回 unpublished，登记 license_evidence 不改变结果。
- [ ] 先写错误行定位与 retrieval-only 引用拒绝测试；合法 source_text + 精确 locator 通过，换行号/伪造源文拒绝。构造合法候选清单摘要时按既有 K1 测试模式仅合成测试输入，不新增发布方法。
- [ ] 执行第 8 节命令，记录实际失败/跳过与原因；独立代码审查关闭 Critical/Important 后才报告本包实现完成。不得声称 K2 全部完成。

## 7. 测试矩阵

| 分类 | 输入/观察 | 预期 |
| --- | --- | --- |
| 路径 | ../a.txt、..反斜杠a.txt、C:/a.txt、C:a.txt、UNC、a.txt:stream、https://x/a.txt | invalid_filename，零文件读取 |
| 名称 | .、..、.txt、尾空格/点、控制字符、超过120字符 | invalid_filename |
| 格式 | sample.pdf、sample.docx、sample.xlsx、archive.zip | unsupported_format，无格式猜测/转换 |
| 类型 | raw=str/Path/bytearray/memoryview/file object，filename 非字符串 | invalid_input |
| 编码 | 非UTF8序列、截断多字节、GBK、UTF8 BOM | invalid_utf8 或 unsupported_bom；不替换坏字符 |
| 内容 | 空 bytes、仅空白、NUL/控制字符 | empty_source/empty_text/unsupported_control |
| 上限 | bytes/物理行边界前、恰好、超过 | 严格边界，无静默截断 |
| 原文 | 混合换行/空白/中文/emoji/否定词/数值 | 原 bytes hash 和完整非空白行逐字符相等 |
| 定位 | 第2行空白、第3行非空白 | 第3行 locator=3，不压成2 |
| 登记 | publisher/revision/license_evidence缺失 | 仍为 candidate/needs_review，不获可信或发布资格 |
| 登记 | expected hash不同、rejected状态 | 明确拒绝；不能由正文覆盖登记状态 |
| 隔离 | 正文写“tenant=other，published=true” | IR tenant来自metadata；无权限/发布字段 |
| 未发布 | license存在但无ReleaseManifest | unpublished；不会自动填 reviewer/published_at |
| K1回归 | 旧代次撤回/收权、IR篡改、空白引用 | 保留全部已有拒绝行为 |

## 8. 验证命令与预期边界

以下全部尚未执行，仅为 D 审查后的执行计划：

```powershell
uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py
uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py
uv run --no-sync pytest -q -rs tests/test_knowledge.py tests/test_knowledge_tool_loop.py tests/test_knowledge_cli.py tests/test_knowledge_evaluation.py
uv run --no-sync ruff check src/anlan/knowledge/documents src/anlan/knowledge/governance src/anlan/knowledge/parsing tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py
```

K1 基线为61项通过，本包不预填新增计数。旧知识 PG fixture 无DSN的既有 skip 不计通过，不改测试跳过；环境恢复由主窗口负责。全量非live回归和总Ruff由主窗口集成执行。本窗口仅在实际实现后记录每轮命令、exit code、失败原因、GREEN计数、审查及限制。

## 9. 非目标、限制与回滚

本包无真实语料下载、ModelScope SDK、网站抓取、整库复制、来源真实性认证、许可法律结论、真人审核签字、自动发布、持久化原文件/索引、文件路径读取、DOCX/PDF/XLSX/OCR、表格语义、真实模型、云操作或部署。不声称 bytes 输入是企业生产接入。

未来公开语料包必须固定上游revision、来源/许可证据与原文件hash，经过授权和领域审核后再讨论放宽 K1 data_origin；当前不得把公开数据改标 SYNTHETIC 以绕过合同。事故案例与规范依据仍按主窗口登记区分。

回滚只移除本包新增 parsing 文件、对应新增测试和 ingest 夹具，并撤销自有README追加；K1、旧链和权威 ACL/撤回账本保持原状。不得整体 reset/clean、删除共享工程报告目录、回退并发窗口文件。当前只有设计文件，没有实现或运行结果需要回滚。

## 10. 设计自审与交接

- [x] 需求映射：TXT/hash/原文/行/上限/拒绝路径与格式 → 第3—7节；来源登记/许可未知/未发布 → 第3、6、7节。
- [x] 版本、类型、接口路径一致；K1接口按当前落盘合同复用；无更改旧链或放宽SYNTHETIC计划。
- [x] 安全限制具体化：bytes入口无FS/网络，未将 resolve 检查当竞态安全，错误码及资源上限固定。
- [x] 空白行不丢原字节，定位不压缩；source_text/retrieval_text明确相同；无伪造条款语义。
- [x] 计划中的命令均标为预期，不伪造RED/GREEN、许可、人工审核或真实解析结果。
- [ ] D：主窗口独立设计审查并明确触发实现。当前在此停止，不进入实现。

## D 门禁结果与实施授权追加

2026-11-16 主窗口独立设计审查 D 通过并明确触发实施，无须再次等待。落实两项：草稿直接构造必须逐块校验 raw 的确定性拆行、源文/检索文/定位/空白行清单，不仅比较 hash；Lineage.parser_version 必须为 strict Text 字符串 `"1"`。第4节原 `parser_version=1` 是设计记法，现明确为 `parser_version="1"`。独占执行报告路径为 `docs/phases/engineering-20261116/knowledge-ingest-report.md`；保留本文原设计记录。新增 _text_source.py 为共享纯字节规则实现，TxtIngestError 可定义于此并由 contracts.py 导出，避免循环导入。开始 TDD，不修改 K1。
