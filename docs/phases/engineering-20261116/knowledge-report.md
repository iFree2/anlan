# K1 独占实施报告

日期：2026-11-16。状态：K1 实现和定向验证完成，独立复审结论见追加；全量集成 Gate 由主窗口负责。只新增 documents/、governance/、test_knowledge_v2* 与 synthetic/knowledge-v2；不改旧知识链/SQL，不提交、不切分支。

## 精确接口和测试小计划（代码前）

1. documents/contracts.py：冻结、extra=forbid、严格字段的 DocumentIR v2，原文件 hash/格式/来源、解析血缘、分离的 source_text/retrieval_text、格式判别定位、父子依赖和表格结构。verify_quote 只校验块及其定位中的连续源文；不宣称语义支持或真实 OCR 正确。
2. governance/policy.py：纯 evaluate_access(document, context, authority, manifest)，返回 allowed/reason；权威 ACL、撤回记录独立于 IR/可回滚发布清单，缺记录拒绝；校验 tenant/user、业务时点、适用范围、审核发布与代次。当前授权校验时点独立于历史业务时点。宿主负责读取最新权威输入，不接受 IR 的权限声明。
3. 合成 JSON 样本及合同测试：严格版本/类型/额外字段、各格式定位与伪造 DOCX 页码、血缘、源文检索文分离、树/依赖/表格、错误定位。
4. 治理测试：允许、跨租户、越权、过期、未发布、未审核、范围、代次错配、缺 ACL/撤回、旧清单回滚后收权/撤回仍拒绝。先实际运行 RED，再实现 GREEN。
5. 定向旧知识兼容回归与 Ruff；PG 环境问题如实报告，不加 skip。主窗口负责全量集成及独立审查。

## 待补：证据、审查、限制与回滚

## 实际命令与结果

| 步骤 | 命令 | 实际结果 |
| --- | --- | --- |
| 合同 RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py` | exit 1；21 failed，均为明确断言 `DocumentIR v2 missing`，非导入收集错误 |
| 合同 GREEN | 同上 | exit 0；21 passed in 0.31s |
| 治理 RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_governance.py` | exit 1；28 failed，均为 `K1 governance missing` |
| 首次治理 GREEN | `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py` | exit 0；49 passed in 0.48s |
| 首次 Ruff | `uv run --no-sync ruff check src/anlan/knowledge/documents src/anlan/knowledge/governance tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py` | exit 1；测试代码 2 处 E501，已修正 |
| 审查修正 RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py -k whitespace tests/test_knowledge_v2_governance.py -k 'whitespace or partial_applicability'` | exit 1；5 failed, 3 passed, 49 deselected；空格误接受、非字符串异常及缺适用标签误接受均复现 |
| 审查修正 GREEN | 两个 v2 测试文件完整运行 | exit 0；57 passed in 0.31s |
| 修正后 Ruff | 同首次 Ruff 命令 | exit 0；All checks passed |
| 旧知识兼容 | `uv run --no-sync pytest -q tests/test_knowledge.py tests/test_knowledge_tool_loop.py tests/test_knowledge_cli.py tests/test_knowledge_evaluation.py` | exit 0；11 passed, 6 skipped in 5.73s |
| 跳过归因复验 | 上述命令增加 `-rs` | exit 0；11 passed, 6 skipped in 2.45s；6 项均来自既有 PG fixture，缺 `ANLAN_TEST_DATABASE_URL`；未改测试添加 skip |

全量 baseline 的既存 setup errors 由主窗口处理；本窗口没有运行或宣称全量通过。旧知识 PG 入库/查询/撤回与 CLI 六项本环境未验证，不能把 skip 算通过。旧知识纯模块、scripted tool-loop 与评测兼容项通过。

## 文件与接口

- `src/anlan/knowledge/documents/__init__.py`、`contracts.py`：DocumentIR、Lineage、Block、Table、五种格式定位、verify_quote。
- `src/anlan/knowledge/governance/__init__.py`、`policy.py`：AccessContext、ACLRecord、WithdrawalRecord、AuthoritySnapshot、ReleaseManifest、AccessDecision、evaluate_access。
- `tests/test_knowledge_v2_contracts.py`、`tests/test_knowledge_v2_governance.py`：合成已见回归。
- `examples/synthetic/knowledge-v2/document.json`、`README.md`：合成合同与未实现边界。
- 本报告是本窗口唯一 docs 输出。旧 knowledge contracts/store/tool/embeddings 的 `git diff -- ...` 输出为空。未 stage/commit、未切分支、未改旧 SQL/总文档；并发窗口文件保留原状。

## 审查与约束落实

- 主窗口独立初审发现 verify_quote 空格误接受（important）：已按实际 RED/GREEN 修正，类型必须 str 且 strip 后非空。tab/newline/空引用及非字符串均返回 False。
- 自审发现只检查 context ⊆ release 会接受缺适用条件：已实际 RED/GREEN 修正为 context 与 release 精确标签集合相同；ACL 必须覆盖全部标签。无通配符/默认适用推断。
- 权威 ACL 与撤回记录独立传入且绑定 logical document/tenant；缺记录默认拒绝。IR 没有 allowed_users/published 等授权字段，额外字段拒绝。
- 历史业务时点与当前授权读取时点分离；旧 IR 和旧 manifest 回滚不能覆盖最新的收权、整文撤回和版本撤回。
- 独立代码审查发现 1 项 Important（发布未绑定完整 IR），修正及复审见追加。

## 限制与回滚

只有 K1 合同及纯治理，不是 K2/K3 完成。真实 DOCX/PDF/XLSX/OCR、原文件保留/真实性验证、真实解析器、文件预览、搜索引擎、知识工具、数据库发布/outbox/缓存失效、领域人工质量验收均未实现。表格表达多级表头/单位/脚注/矩形行，合并/公式模型待后续解析包。原文件 SHA256 字段目前仅校验格式；样本 source/config hash 为占位值，不证明存在相应源文件。IR 摘要则实际重算并绑定清单，见下方审查修正。引用匹配仅校验连续转录与已给定位，不证明定位真实性、OCR 正确或主张语义支持。

宿主必须对每次决策原子取得最新 ACL、撤回记录及当前选定发布清单，不能从旧索引或缓存回滚这些输入；checked_at 仅绑定本次调用，纯函数无法证明后端没有伪造/重标旧记录。每个扩展文档/缓存命中仍需重新治理。quality 标记不等于领域签字，reviewer fixture 只是合成输入，无真实人工审核结论。

回滚只移除本报告列出的新增自有文件及将来的显式装配；当前未装配旧入口，不需 SQL 回滚。不得整体 reset/clean 或删除 engineering-20261116（并发报告在同目录）；不得回滚独立权威 ACL/撤回账本。零真实模型、零部署、零云操作、零新增平台或模型安装。

## 独立代码审查修正（最终代码稳定）

review_k1 只读独立审查发现 1 项 Important：仅绑定原文件 hash、版本与代次，不能阻止同代次 IR 的源文/检索文本/定位/血缘被替换。已先新增 4 项篡改测试，运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_governance.py -k reviewed_ir` → exit 1，4 failed, 29 deselected in 0.61s（实际复现错误 allowed=True）。然后增加 DocumentIR.content_digest() 和 ReleaseManifest 必填 ir_sha256，治理时重算比较。

规范序列化覆盖完整已验证 IR 和默认字段：JSON sort_keys=True、ensure_ascii=False、separators=(comma,colon)、allow_nan=False，UTF-8 SHA256。发布清单应在人工审核后记录摘要；调用时不能根据未审核 IR 自动重写清单。摘要绑定不等于原文件或发布者认证。

修正后完整 v2 命令 `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py` → exit 0，**61 passed in 0.41s**。限定路径 Ruff 原命令 → exit 0，**All checks passed**。此前主窗口并发看到 4 个失败是此轮实际 RED 期间，本轮已 GREEN。

独立复审结论：review_k1 对修正后代码只读复验，原 Important 已关闭，**无剩余 Critical/Important**；完整 IR 篡改返回 release_mismatch；独立执行 61 项测试及 Ruff 均通过。当前 K1 文件已稳定，可由主窗口继续统一集成复验。没有扩展 ModelScope 数据摄取或 K2/K3。
