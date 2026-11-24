# K2a UTF-8 TXT 候选摄取独占报告

日期：2026-11-16。状态：实现、定向验证和独立代码审查完成；主窗口负责最终独立复验。范围严格限 K2a，不表示 K2/K3 全部完成。

## 设计与授权

设计 `knowledge-ingest-design.md` 经主窗口 D 审查通过后才实施；两项约束已落实：草稿直接构造须与同一 raw 确定性拆行完全一致，parser_version 为严格字符串 `"1"`。原设计保留并追加门禁结果。未切分支、未 stage/commit、未创建其他窗口、未改旧知识链/K1/SQL或总文档。

## 交付文件与行为

- `src/anlan/knowledge/parsing/__init__.py`：限定范围说明。
- `parsing/contracts.py`：SourceCandidate、LicenseEvidence、TxtIngestMetadata、TxtIngestDraft；严格冻结合同；来源 URL 只做结构检查，不联网；未知来源/许可仍是候选。
- `parsing/_text_source.py`：256 KiB/4096物理行固定界限、受限逻辑名、严格UTF-8与BOM/控制字符拒绝、CRLF/LF/CR精确拆行、块/定位/血缘和固定错误码。
- `parsing/text.py`：纯 `parse_txt(raw:bytes, filename, metadata, candidate)`；零磁盘或网络IO，返回保留原字节的未审核/未发布草稿。
- `tests/test_knowledge_v2_parsing.py`：69项已见合成回归。
- `examples/synthetic/knowledge-v2/ingest/sample.txt`、`candidate.json`：来源和许可未知的明确合成夹具。
- `examples/synthetic/knowledge-v2/README.md`：追加 K2a 使用边界。
- 本报告与 `knowledge-ingest-design.md` 追加段是本包 docs 输出；不覆盖 K1 报告。

非空白物理行逐字保留，包括前后空白和真实换行；空白行原字节保留、原始1-based行号记入 omitted_blank_lines，未压缩后续定位。raw/source hash实际计算，IR内容摘要复用K1。草稿直接构造重算并比较 hash、source_format/uri、完整blocks（包括源文/检索文/定位/顺序/ID/依赖）、空白行列表及确定性血缘，不能只改 hash 伪造通过。候选许可、正文指令均不能授权或发布。

## 实际 RED/GREEN 与检查记录

| 步骤 | 实际命令 | 结果 |
| --- | --- | --- |
| 来源合同 RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k contracts` | exit1；16 failed,49 deselected in0.56s，缺 parsing 包的明确断言 |
| 来源合同 GREEN | 同上 | exit0；16 passed,49 deselected in0.23s |
| 解析首轮 RED（夹具问题） | `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k 'exact or rejects or unpublished'` | exit1；48 failed,16 deselected,2 errors；超大 bytes 自动测试ID造成 pytest setup 问题，已改短ID，没有改业务断言 |
| 修正测试ID后解析 RED | 同上加 `--tb=line` | exit1；49 failed,16 deselected in0.44s，缺parser/错误类型等明确缺失 |
| 独立观察草稿一致性 RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k exact_direct_draft --tb=short` | exit1；4 failed,1 passed,60 deselected in0.78s；hash-only实现未拒绝伪源文/检索文/定位/空白行，D约束真实复现 |
| 其余解析 GREEN | `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k 'not exact_direct_draft' --tb=short` | exit0；60 passed,5 deselected in1.51s |
| 加入逐块校验后 GREEN | `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py` | exit0；65 passed in0.62s |
| 首轮 Ruff | `uv run --no-sync ruff check src/anlan/knowledge/parsing tests/test_knowledge_v2_parsing.py` | exit1；2处I001，随后仅在自有文件用--fix修正 |
| published 类型 RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py -k 'published_requires or readonly_fixed'` | exit1；1 failed,1 passed,65 deselected in0.43s；Pydantic Literal False接受整数0，加入before严格bool校验 |
| 类型修正联合 GREEN | `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py` | exit0；128 passed in0.97s |
| 加合法非text草稿拒绝/合成夹具回归最终 GREEN | 同上一命令 | exit0；**130 passed in3.28s**，K1 61 + K2a 69 |
| 最终限定 Ruff | `uv run --no-sync ruff check src/anlan/knowledge/documents src/anlan/knowledge/governance src/anlan/knowledge/parsing tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py` | exit0；**All checks passed** |
| 旧知识兼容 | `uv run --no-sync pytest -q -rs tests/test_knowledge.py tests/test_knowledge_tool_loop.py tests/test_knowledge_cli.py tests/test_knowledge_evaluation.py` | exit0；**11 passed,6 skipped in2.10s**；6项既有PG fixture缺 ANLAN_TEST_DATABASE_URL，未添加skip，不计通过 |

没有全量通过声明；主窗口恢复PG和运行集成Gate。本窗口没有读取/打印DSN或覆盖环境配置。

## 安全/审查与限制

自审已修复公开状态布尔类型及草稿完整一致性。独立审查结果后续追加。受限文件名拒绝绝对/相对路径、UNC、穿越、URL、ADS及非txt后缀；不执行文件读取，所以没有以resolve替代打开竞态保护。输入bytes必须由可信宿主已安全取得；256KiB限制只约束parser输入，不能替宿主限制读取前的内存分配。

来源登记的publisher/revision/license/evidence均为宿主声明，结构校验不代表源文件或许可真实性。未访问ModelScope，未下载真实语料，无真实许可、真人审核或再分发授权结论。raw_bytes只在内存保留，未持久化到原文件仓库；synthetic://URI仅是草稿资产标识。SYNTHETIC边界没有放宽，不允许把公开资料改标合成来绕过。无实际路径读取CLI/HTTP、DOCX/PDF/XLSX/OCR、语义条款/表格、搜索/索引/发布存储、生产认证、真实模型、网络、部署或云操作。

TxtIngestError只有固定code和消息，UTF8错误不链接包含原字节的解码异常；Pydantic直接构造的ValidationError仍可能带输入，模块不记录或展示，未来外部入口必须脱敏。没有声称合法URL就可信或许可完整。

## 回滚

只移除新增parsing/、test_knowledge_v2_parsing.py和ingest夹具，撤销自有README追加；K1与旧链未装配此parser，不需SQL回滚。不整体reset/clean，不删共享工程报告目录，不回退其他窗口文件或权威ACL/撤回账本。本包不产生业务状态、索引发布或外部副作用。

## 独立代码审查最终结论

review_k1 只读审查通过：**无 Critical/Important**。独立实际复验 K1+K2a **130 passed**，限定Ruff **All checks passed**；另用独立参考拆行算法检查 **14,070组** 混合字符输入，行划分与原文保留一致（此项是审查窗口额外验证，不混入130项pytest计数）。确认 bytes 入口无IO、固定资源上限、严格UTF8、直接草稿一致性与候选不自动发布。未修改文件、未调用模型/网络/PG。

本包实现、限定检查和独立代码审查完成，代码稳定，供主窗口独立复验与集成。PG六项仍未验证；后续真实来源/路径读取/多格式/发布/检索不属于本次完成结论。
