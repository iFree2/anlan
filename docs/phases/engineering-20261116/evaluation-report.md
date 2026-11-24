# E1 / P9-WP01 独占包报告

## 接口与测试小计划（实施前）

- 所有权：新增 `src/anlan/evaluation/`、`evals/enterprise-eval-v2/`、`evals/evaluate_enterprise.py`、`tests/test_enterprise_evaluation.py` 及本报告；不改旧报告、工作流、SQL、总文档和他人文件。
- 采用严格 Pydantic v2 合同：Manifest 固定 schema/scorer、安全全集、非空且唯一 required_case_ids；版本含代码/prompt/模型/知识/数据/评分器、环境、运行与固定时点、请求限制及尝试数。
- CaseResult 分离结构/语义/人工、安全全集、错误、token/费用/延迟；人工未审核 pending；未知计量为 null。Report 根据原始记录重新聚合，不接收外部 passed 标志。
- 固定安全项：越权、事实编造、自动批准、责任认定、告警修改、无证确定、无效制度、旧 revision、告警链阻断。缺检查 pending；任一 fail 独立阻断。空/缺样本不可 pass，重复 ID 拒绝。
- CLI 仅离线读取严格 bundle 或适配历史 materials-v1 报告；输出独占创建，不覆盖源文件；结构匹配不推导语义/人工/安全通过。
- RED：先写版本严格性/重复/空漏/全部安全独立阻断/人工 pending/未知计量/历史适配不改源/CLI 的行为测试并实际运行；GREEN 后运行新入口、相邻旧评测与 Ruff。
- 合成样本仅为已见合同回归；不制造人工金标、未见集、领域评审或生产效果。仅闭环 E1，不代表 P9 完成。

## 实测与审查

下文为真实运行记录；独立审查后修订另列。

## 实际实施与验证结果

- 新增包：`contracts.py`（Manifest/Check/CaseResult/Bundle/Provenance），`report.py`（重新聚合与独占落盘），`adapters.py`（materials-v1 离线保守适配），`__init__.py`（公开入口）。无数据库依赖、模型调用和业务写入。
- 新增入口：`evals/evaluate_enterprise.py`。新合同的 schema/scorer 版本均固定，所有字段额外项拒绝；必测清单非空且唯一，重复或目录外案例拒绝。固定 9 安全项，缺失按 pending 聚合，失败逐项列出，严重阻断先于任何平均分。空/漏样本/漏检查/缺人工/缺固定时点不能通过。
- 新增测试：`tests/test_enterprise_evaluation.py`，42 项。人工已审核 fixture 仅用于验证 API 约束，不是产出的人工标签或领域审核记录。交付的样本人工全部 pending。
- 新增资产：`evals/enterprise-eval-v2/{README.md,manifest.json,bundle.json,offline-report.json,legacy-adapted-report.json,adjacent-routing-report.json}`。

### 实际命令与结果（2026-11-16，Asia/Shanghai）

1. 首轮 RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation.py` → **36 failed in 1.85s**；失败明确为尚无 `anlan.evaluation`，测试通过 pytest.fail 报功能未实现，不是收集失败。
2. 首轮实现后 → **1 failed, 35 passed in 1.96s**。核对历史第三例 exact_match=false，修正测试原先误把历史整体预期为 pending 的假设，保留真实 blocked；未修改源报告。随后同命令 → **36 passed in 1.27s**。
3. 适配来源约束的行为 RED：同测试命令 → **1 failed, 38 passed in 2.30s**，`DID NOT RAISE ValueError`（在线来源进入只支持离线的适配器）。新增 offline/零请求校验后 → **39 passed in 4.32s**。
4. 未知固定时点 RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation.py -k unknown_historical_fixed_time` → **1 failed, 39 deselected in 0.38s**，fixed_at=null 尚不支持。改成必填 nullable 并在 null 时门禁 pending，避免把历史报告创建时间冒充业务固定时点。新产物初稿在交付前重新生成；历史源文件从未写入。
5. 审查修订前定向及相邻回归：`uv run --no-sync pytest -q tests/test_enterprise_evaluation.py tests/test_evaluation.py tests/test_conversation_evaluation.py tests/test_knowledge_evaluation.py tests/test_rag_evaluation.py` → **56 passed in 12.00s**，无跳过、无 PG setup errors。前一轮添加 fixed_at 测试前为 55 passed，该轮为 56；审查修订后最终为下述 58。
6. `uv run --no-sync ruff check src/anlan/evaluation evals/evaluate_enterprise.py tests/test_enterprise_evaluation.py` → **All checks passed!**。过程中发现过 3 行 E501，均在自有文件修复；未触及其他窗口代码。
7. `uv run --no-sync python evals/evaluate_enterprise.py --bundle evals/enterprise-eval-v2/bundle.json --output evals/enterprise-eval-v2/offline-report.json` → **exit 2**, gate=blocked，cases=3。
8. `uv run --no-sync python evals/evaluate_enterprise.py --legacy-materials docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json --manifest evals/enterprise-eval-v2/manifest.json --output evals/enterprise-eval-v2/legacy-adapted-report.json` → **exit 2**, gate=blocked，cases=3。2 是预期的非通过门禁退出码，报告正常保存。
9. `uv run --no-sync python evals/evaluate_conversation_routing.py --input evals/conversation-routing-v1/scripted-results.json --output evals/enterprise-eval-v2/adjacent-routing-report.json` → **exit 0**，原入口原格式另存输出，无真实模型。

### 离线报告事实

3 条既有 SYNTHETIC 已见回归；最终结构、语义、人工各 3 pending。旧 exact_match 是问题集合正确性，独立保存到 legacy_issue_set：2 pass / 1 fail（第三例旧规则未识别含糊材料）；该独立正确性失败使 gate=blocked，不再误标结构无效。安全检查全集 9 项，每例均未测，共 27 pending；不能把 blocker 列表为空理解为安全通过。历史延迟可用并注明 nearest-rank；token/费用均未知 null，未给未知费用填 0。fixed_at=null，因为历史未记录业务固定时点。request_limit/request_attempts 为 0，代表本次离线回放零 provider 请求。

旧文件字节 SHA256（转换前 Python 与验证后 Get-FileHash 一致）：
`docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json` = `a466a2a12edf9cd9209129d84147fa39da26fb8efd2052de3f23d77002dadf01`。
报告内 provenance.source_sha256 是**规范化 JSON 内容摘要**，不是原字节摘要；其含义已在 provenance 和 README 明示。

### 审查与门禁边界

- 自检：逐项核对蓝图审查约束 E1（安全全集/required IDs/重复/空漏不通过），同时检查历史文件不写入、无隐式在线调用、无生产/部署/云操作。
- 独立审查：按 requesting-code-review 技能派发只读审查；发现漏整例时总量/分位数未置未知的重要问题。父窗口独立审查另发现旧 issue-set 正确性混同结构指标的问题。两项均先补回归并实际观察 RED 后修复，复审结论另附。
- 本窗口仅声明 E1/P9-WP01 的工程合同和离线入口可运行。不声明 P9 验收全部通过、生产安全、真实企业效果或人工认证。
- 全量基线既存 PG setup errors / 其他失败的环境恢复由主窗口负责；本窗口没有改测试跳过规则，也未将本次定向结果称为全量回归。
- 聚合器依赖宿主提供可信的评分记录、冻结 manifest 和 reviewer 标识；不自动验证 reviewer 真实身份，也不执行语义推理。E2 的逐主张核验/领域标注/人工导入/Judge 校准、未见集、场景扩充、完整 E2E 重复/对照/影子运行仍待验。

### 保护与回滚

未 stage/commit、未切分支、未创建额外聊天、未改旧 SQL/评测脚本/工作流/总文档。其他窗口正在并发新增 knowledge/tools 等文件，不纳入本包回滚。回滚仅移除本包新增 `src/anlan/evaluation/`、`evals/enterprise-eval-v2/`、`evals/evaluate_enterprise.py`、`tests/test_enterprise_evaluation.py`（必要时先保留报告证据）；无需数据库迁移或修改旧入口。禁止 git reset/clean、整体 restore 或删除共享 `docs/phases/engineering-20261116/`。本报告可保留作为交接证据。

### 独立审查修订 RED/GREEN

- 命令 `uv run --no-sync pytest -q tests/test_enterprise_evaluation.py -k 'legacy_false_issue_set or missing_required_case'` → **2 failed, 40 deselected in 0.44s**。分别实际捕获 `structure=fail`（预期 pending）以及漏整例仍输出 p50=12.0（预期 null）。
- 将旧 exact_match 独立保存在 CaseResult.legacy_issue_set / report.legacy_metrics.issue_set；结构未重新 schema 验证时 pending。已知集合正确性失败独立阻断，绝不冒充结构失败。
- 必测目录缺任一案例时，完整 token/费用总量和延迟分位数均 null；known_* 与测量案例数保留已有部分事实。
- 修改后运行 E1 → **42 passed in 1.79s**。随后 Ruff 发现 3 个新增 E501，已在自有文件格式化修复；最终联合回归与 lint 结果另附。
- 两个新入口在修订后重新实际运行并生成最终产物，均 **exit 2**, gate=blocked, cases=3。源历史文件仍不写入。

### 最终复验与复审

- 最终命令 `uv run --no-sync pytest -q tests/test_enterprise_evaluation.py tests/test_evaluation.py tests/test_conversation_evaluation.py tests/test_knowledge_evaluation.py tests/test_rag_evaluation.py` → **58 passed in 13.50s**，其中 E1 42 项；无跳过。
- 最终命令 `uv run --no-sync ruff check src/anlan/evaluation evals/evaluate_enterprise.py tests/test_enterprise_evaluation.py` → **All checks passed!**。
- 独立复审结论：两项重要问题均已修复，无剩余 Critical / Important。复审方实际运行 **42 passed**，并重新聚合确认两份生成报告与当前代码完全一致、均 blocked。
- 交付判定：E1 工程合同/离线报告入口完成；领域数据、真人审核、P9 后续验收仍待验。零真实模型、零部署、无云操作。

### 最终自有源码 SHA256

- `src/anlan/evaluation/__init__.py` = `348a484eb829d7d08e4f192ba453a3ec804b25c43032b1c2e27a11da9d52c462`
- `src/anlan/evaluation/adapters.py` = `0b3c8cdae47ee3bb70a3b8b6080ee7d81b1eab1ffd3be79ad0d3e6c330a40623`
- `src/anlan/evaluation/contracts.py` = `1c8685df46f825831173753aacee659237fa4a2d64d9ea636d58925a30ff83ee`
- `src/anlan/evaluation/report.py` = `0f722bc3d175022ff4da5daa75e3e8b32f401b033f6ecc00783d441d5722d5f2`
- `evals/evaluate_enterprise.py` = `3f44f5d2f33a2523c9d827512485fa1dd497b205bac635244845cc985d60cc4c`
- `tests/test_enterprise_evaluation.py` = `370d8d30c9f91d6e87f3277d86195838df2393f4d5ebf602270a90d5df8226a5`

最终源历史文件字节 SHA256：`a466a2a12edf9cd9209129d84147fa39da26fb8efd2052de3f23d77002dadf01`（与实施前一致）。
