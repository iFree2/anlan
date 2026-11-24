# K3→E1 最小真实离线集成评测包报告

日期：2026-11-17，Asia/Shanghai。设计文件 `knowledge-evaluation-design.md` 经父窗口 D 审通过，按受限三场景实施。实现、CLI、观测重评分、篡改回归已交付；本包冻结，不扩新包。

## 交付文件及真实执行范围

新增 `src/anlan/evaluation/{knowledge_contracts.py,knowledge_runner.py,knowledge_scoring.py,knowledge_verification.py}`，独立入口 `evals/evaluate_knowledge_v2.py`，`tests/test_enterprise_knowledge_evaluation.py`（最终30项），独立输入目录 `evals/enterprise-eval-v2/knowledge-runner-v1/`（cases.json、3个实际TXT、table-ir.json、README）。未修改任何 K/工具/工作流源码、SQL、E1合同或旧E2源文件/入口/产物。

三个真实执行场景：

1. `k3e-normal`：实际 UTF-8 TXT bytes→原生 parse_txt→needs_review/published=False draft→独立显式 SYNTHETIC release/ACL/withdrawal→原生 LocalBM25 search→用实际命中调用 get_clause。引用保留第1行完整CRLF、物理行号、原字节SHA256、IR摘要和发布绑定。
2. `k3e-withdrawal`：A/B实际TXT各自原生解析；真实 LocalBM25 返回后仅对内存权威A做withdrawn false→true/revision 1→2；原生K3在vector前重建语料。vector是明确的DeterministicRankProvider替身，实际只接收B。最终packet不留A；随后以原A/旧release做get_clause仍拒绝。观测保存实际provider候选、排名、ledger快照、mutation、resolver和API返回。
3. `k3e-table`：独立 SYNTHETIC 矩形IR，非TXT解析产物、没有实际XLSX输入。真实query_table做Decimal筛选 >=10 m，只保留item0/10，完整单元格A3/B3、headers/units/footnote和derived_from_reviewed_ir定位。不会声称读取/解析了workbook。

合成发布 reviewer='SYNTHETIC-evaluation-fixture' 仅是策略刺激，不是领域人工签字；draft与lineage没有变成人工审核通过。没有真实embedding/模型/网络/PG/云/部署。

## 实际 RED/GREEN 记录

以下记录均来自实际工具输出，不把预期输出当结果。

- 首轮 `uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py` → **7 failed in 0.49s**。全部在测试体明确失败于新运行器尚不存在，无importorskip、PG或收集错误。实现原生链及初版评分/校验后，同命令 → **7 passed in 4.91s**。
- 初版紧凑代码的Ruff报导入/行长/多语句问题，均只在自有新文件整理、format，最终限定Ruff通过；不将中间lint失败隐去。
- 请求绑定/取消 RED：`... -k 'event_request or cancel_keeps'` → **2 failed, 7 deselected in 0.96s**：事件尚无显式request_id（根合同拒绝额外字段），取消时未保留已有trace。新增严格producer/request_id、每API绑定及取消partial trace。
- 固定筛选刺激 RED：`... -k changed_filter` → **1 failed, 9 deselected in 0.75s**：把>=10改>=0并同步api_started仍无错误。补固定搜索/筛选/行限制刺激校验。上述修复后 → **10 passed in 4.12s**，Ruff通过。
- 补静态夹具预验证、已有输出拒绝覆盖、独立重签trace负例和旧E2冻结检查后 → **13 passed in 5.26s**。
- 独立审查源/版本/selector RED：`... -k source_selector` → **3 failed, 13 deselected in 1.57s**。复现后续get改B、resolver伪造返回块、provider伪造版本仍安全pass。补selector与实际命中/撤回A/table绑定、resolver完整原块比对、原生provider版本/packet provider_versions/tokenizer绑定；随后 → **16 passed in 7.09s**。
- 必需取证/发布/泄漏/表格 RED：`... -k complete_resolver` → **4 failed, 16 deselected in 8.15s**。复现删全部resolver、伪造release元数据、related_key泄露A、伪造首表单元格仍未拒绝。
- 每请求最新权威 RED：`... -k per_api_current` → **5 failed, 20 deselected in 3.42s**。分别复现release_fingerprint、ACL revision、withdrawal revision、checked_at伪造，以及删第二请求全部ledger_read仍安全pass。
- 修复：逐API ledger读取数必须等于packet.authority_reads且>0，resolver调用数等于projection_reads，每个输出item都必须有本API实际resolve且返回块等于目录；逐item绑定本API最新ledger的release fingerprint/checked_at/ACL/withdrawal revision；所有表格单元格值、table_key、row_index、完整locator绑定IR；撤回key/digest检查覆盖两包items/required_keys/table_rows/issues.related_key/audit.key_digest。缺依赖pending+integrityerror，实际已观察泄漏独立安全fail。修复后 → **25 passed in 10.31s**。
- 增加后续拒绝packet的related_key/audit泄漏负例，父窗口实际 **27 passed in 11.22s**；其独立integration_review同样 **27 passed**、限定Ruff通过，并重放7项负例，确认三项Important全部关闭、无剩余Critical/Important。
- 补最后来源身份/读取参数自检 RED：`... -k source_identity` → **3 failed, 27 deselected in 2.18s**。source_uri/title及ledger调用checked_at标签原先未绑定。补与原DocumentIR/实际AuthoritySnapshot的比对，纳入最终30项测试。

## 最终相邻回归与Ruff

真实命令：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_knowledge_evaluation.py tests/test_enterprise_evaluation.py tests/test_enterprise_evaluation_runner.py tests/test_knowledge_v2_parsing.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_retrieval.py tests/test_knowledge_v2_retrieval_security.py tests/test_knowledge_v2_retrieval_tables.py
uv run --no-sync ruff check src/anlan/evaluation evals/evaluate_knowledge_v2.py tests/test_enterprise_knowledge_evaluation.py
```

结果：**267 passed in 23.06s**；**All checks passed!**。无跳过。之前264 passed in 33.36s是最后三项加固前结果。最终267项包含本包30项、E1/E2及K2/K3相邻回归；不是本窗口宣称的全库回归。

旧E2冻结测试实际按其已交付run-index的源码SHA256比对原contracts/report/runner/runner_contracts/offline_fixtures/scoring/runner_verification和evals/evaluate_enterprise.py，并对旧8场景原产物执行verify_run，均通过。

## 真实CLI与交付产物

实际命令：

```powershell
uv run --no-sync python evals/evaluate_knowledge_v2.py --catalog evals/enterprise-eval-v2/knowledge-runner-v1/cases.json --artifacts-dir evals/enterprise-eval-v2/knowledge-runner-results
```

实际 **exit 2**，gate=pending，cases=3。新产物目录：

`evals/enterprise-eval-v2/knowledge-runner-results/983a5a6f-2c66-430c-adbc-3e32f20e3865/`

实际调用 `verify_knowledge_run(run-index.json)` → **valid=true, errors=[]**。报告事实：3/3样本完整；结构3 pass；语义与人工各3 pending；27条安全记录中 **1 pass / 26 pending**；errors=[]；token/费用全部null。唯一安全pass来自实际两路间撤回刺激；正常源文一致不冒充安全全集通过，suite正确保持pending。

产物包含严格manifest与独立富版本run-index、每例原字节副本/input/observation/trace、bundle/report。观测内保存实际draft、IR、原生EvidencePacket、ledger/provider/resolver和mutation事件；trace含producer/case/run/request/seq和实际载荷。校验器重parse无副作用TXT并验证原始字节和IR，再逐API检查事件、取证、当前发布/权限及版本，从observation重新逐例score并完整比较bundle，最后重新聚合E1 report。不能只改bundle.errors或安全pass后重算两文件hash来掩盖观测。

## 审查与限制

独立首审与父窗口均找到可复现Important，已按上述真实RED/GREEN修复。原复审worker因额度限制没有返回最终结论；**没有将该失败记为审查通过**。最终三项Important的关闭以父窗口明确提供的integration_review复审为据：独立27项通过、限定Ruff及实际suite verify有效、7负例均按预期拒绝/独立fail，无剩余Critical/Important。之后的3项来源身份加固已实际RED/GREEN并通过最终267项回归，报告明确区分这两个检查时点。

SYNTHETIC数据均为开发者已见工程回归；human/语义和其他未测安全项保持pending，没有企业金标、未见集、真实embedding/LLM质量、法规效力、生产发布/撤回存储或现场效果结论。表格地址只从合成审核矩形IR推导，不认证原workbook。SHA256/重评分用于完整性与因果复核，不认证恶意可信宿主全盘重签的产物。

每例独立内存ledger；仅撤回例有显式合成状态transition。原字节、IR/目录输入只读，其他例无权限变更。只读本包固定可信根，不从catalog.parent自动授权；输出新UUID目录/文件独占创建。测试用socket连接哨兵确保原生离线执行不触发网络；没有HTTP/OTLP/PG、真实模型或依赖安装。

延迟只为本地parse/装配/原生检索/观测组装阶段的perf_counter实测，不含最终评分/报告序列化，也不代表真实embedding或生产端到端延迟。零provider模型请求与未知token/费用分开记录。

## 冻结与回滚

本包现冻结。未stage/commit、未切分支、未新建聊天，未改旧SQL/工作流/K/工具/M2或总文档，未回退并发修改。回滚仅移除本包新增knowledge_*评测模块、新CLI、新测试、新输入与新独占结果目录（先保留证据）；无需修改旧E1/E2或K接口，也不恢复任何真实撤回权限记录。禁止整体reset/clean/restore或删除共享engineering-20261116目录。

## 最终自有源码SHA256

- `src/anlan/evaluation/knowledge_contracts.py`: `09a1d3a9520ce10612c4dc6080168c3b5009e75dbcee1dfdb24592f2a3d50b11`
- `src/anlan/evaluation/knowledge_runner.py`: `0109d122c5f4664ebac38a5f851a8244c1b4bf31e9f6a4554fc541aaff1f3044`
- `src/anlan/evaluation/knowledge_scoring.py`: `2e244a1871240bf863237a529db2e387c17d9985e4b256878919e28e3696f0de`
- `src/anlan/evaluation/knowledge_verification.py`: `efb18ff302722ed430891bf47f77e6da153f4efa5fc57cb40ecd6de705b69e41`
- `evals/evaluate_knowledge_v2.py`: `38987192c19e2fe114e29faf85ad15b3feea5c55715201d945e6feb372ff941e`
- `tests/test_enterprise_knowledge_evaluation.py`: `7877ef2cd2ea04c1bf85530eeb2927fbe093d998b0c07ed991f11e4d5b8af1df`
