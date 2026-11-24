# E2a 真实离线运行器包报告

日期：2026-11-16，Asia/Shanghai。设计：`evaluation-runner-design.md`，父窗口独立 D 审通过并授权三项修订后直接实施。本包仅闭环 8 场景的工程执行/证据/评分通路，领域人工、未见集、完整知识业务链和 P9 后续验收仍待验。

## D 审三项约束

1. fact-normal 没有旧 revision 攻击，stale_revision 始终 pending；正常绑定一致只作 diagnostics。
2. E1 Manifest 原字段及 extra=forbid 未改；文件/prompt/lock/dirty/fixture 丰富摘要放严格 run-index sidecar，用 manifest SHA256 关联。
3. 固定宿主夹具允许根 `evals/enterprise-eval-v2/runner-v1`，catalog 与 fixture resolve 后必须在该根；不以任意 catalog.parent 自动授予访问范围。

## 自有文件

新增 `src/anlan/evaluation/{runner_contracts.py,offline_fixtures.py,runner.py,scoring.py,runner_verification.py}`；只修改自有 `evals/evaluate_enterprise.py` 增加互斥 --run-scenarios / --artifacts-dir 模式，旧模式保留。未修改 E1 contracts/report 或旧业务、工具、知识、LLM、trace 源码。

新增 `tests/test_enterprise_evaluation_runner.py`（21 项）及固定 `evals/enterprise-eval-v2/runner-v1/{cases.json,materials.json,document.json,facts/*.json,README.md}`。新增真实交付产物目录 `evals/enterprise-eval-v2/runner-results/123a7fc5-343f-48f6-9aad-629ed41f2138/`。设计文件落实 D 审修订；本报告为独占包结果。

实际调用路径：事实分支 WorkflowService/OfflineAnalyzer/MemoryRegistry → check_facts_agent → 原 Registry/Policy/Executor/FactTools；治理分支 DocumentIR/AccessContext/AuthoritySnapshot/ReleaseManifest → 原 evaluate_access。脚本 ModelTurn 是协议刺激，无 gateway/model/provider 请求。治理与事实分支分别测原生边界，不拼组件分数声称 K1 已进入旧知识工具链。

## 实际 RED/GREEN 记录

以下命令均为真实执行；首轮错误测试装配经过纠正后才将缺模块作为 RED，不把 PG/环境 setup error 当业务失败。

- 初次 `uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py` → **2 failed, 7 errors in 1.43s**：新模块缺失在 async fixture setup 中暴露。调整测试装配使缺失在测试体明确失败，重跑同命令 → **9 failed in 1.06s**，全部明确 `E2a native offline runner is not implemented`，无收集/环境错误。
- 首轮实际实现同命令 → **9 passed in 12.14s**。首次 Ruff 报 13 项导入/行长问题，均只在自有文件修复。
- 证据因果/trace RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py -k 'recomputes or forged_native'` → **2 failed, 9 deselected in 5.62s**。重算 bundle/report hash 后 verifier 仍接受伪填安全 pass；篡改 native payload run_id 后外壳一致仍通过。修复为从保存 observation 逐例重新 score_observation 并与 bundle 全字段比较，以及原生 trace 关联校验。
- 安全依赖/畸形响应/工具错误抹除 RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py -k 'malformed or erase_tool'` → **3 failed, 11 deselected in 5.10s**。分别复现 structure 无效却给安全 pass、results=null 触发 TypeError、删除 tool:data_error 并重算 bundle/report hash 后 verifier 仍 valid。现已要求结构+输入+原生调用+必需 diagnostics 完整才评分；失败依赖保持 pending+integrity error；结构无效后不遍历畸形结果；工具错误不能从 bundle 侧删除。
- 原生协议合同 RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py -k invalid_protocol` → **2 failed, 14 deselected in 3.52s**，未知 stop_reason 和任意 summary dict 原先仍 structure pass。补 stop_reason Literal、FinalAnswer 验证、结果 call_id 必需等校验。
- 全 trace 伪壳 RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py -k replacing_whole` → **1 failed, 16 deselected in 3.38s**。整条正常 trace 替为 made_up event / unrelated-run，重算 trace hash 后仍 valid。现核验真实起止、拒绝/治理事件及 fact 原生 analysis/model/tool/loop 记录、task/correlation/revision/source/结果绑定。
- 上述修复中曾 **1 failed, 16 passed in 23.79s**：原始 input 文件在 Windows 写 CRLF，单纯按 LF 重建字节摘要使真实观测 pending。新增独立 canonical input_content_sha256 供 scorer 校验；原 input_sha256 仍在 verifier 校验原始字节。之后 → **17 passed in 12.54s**，Ruff 通过。
- 夹具预验证 RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py -k invalid_fixture` → **1 failed, 17 deselected in 1.49s**，坏 DocumentIR 原先在部分场景已执行后才暴露。现在所有材料/事实/知识/治理夹具在创建输出目录和原生执行前验证；另验证取消传播并保存 partial index、已有运行目录不可覆盖。随后 → **20 passed in 14.72s**。
- 模型 trace step RED：`uv run --no-sync pytest -q tests/test_enterprise_evaluation_runner.py -k trace_model_step` → **1 failed, 20 deselected in 3.60s**，把真实模型事件 step 改成 99 并重算 trace hash 原先仍通过。现逐条匹配 native.model_attempts 的 step/attempt_id/error/usage。

## 最终真实验证

命令：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_evaluation.py tests/test_enterprise_evaluation_runner.py tests/test_tool_loop.py tests/test_tool_model.py tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py
uv run --no-sync ruff check src/anlan/evaluation evals/evaluate_enterprise.py tests/test_enterprise_evaluation.py tests/test_enterprise_evaluation_runner.py
```

结果：**146 passed in 18.81s**；**All checks passed!**，无跳过。前一轮 145 passed in 17.25s 是加入 step 篡改测试前结果，以最终 146 为准。原 E1 的 42 项（包括旧 --bundle 独占落盘测试）包含在本轮内。本窗口未宣称全库回归；主窗口负责并发整体集成。

实际入口命令：

```powershell
uv run --no-sync python evals/evaluate_enterprise.py --run-scenarios evals/enterprise-eval-v2/runner-v1/cases.json --artifacts-dir evals/enterprise-eval-v2/runner-results
```

实际 **exit 2**（非通过门禁的预期退出码），cases=8，gate=blocked。另以 Python 实际调用 `verify_run` 对上述 run-index 验证 → **valid=true, errors=[]**。

## 实际报告事实与证据

- 结构：7 pass、1 pending；跨租户入口拒绝没有原生结果，故不伪造结构通过。
- 语义/人工：各 8 pending。未生成真人标签或声称自由文本主张得到语义支持。
- 安全全集 72 条记录：5 pass、67 pending。5 项通过分别来自对象越界拒绝、跨租户拒绝和三个实际治理刺激；未触发旧 revision、批准/责任认定、告警修改/链路、事实编造、无证确定等项保持 pending。
- 错误：`e2a-fact-tool-error` 保留 **tool:data_error**，因此 blocked。错误不能因符合注入预期而被抹成通过。
- token/费用：全部 null，零 provider 请求独立记录，不将未知计量伪装为 0。
- 延迟：8 条为本地 case 装配/原生调用/输入与 trace 落盘、截止 observation 组装前的实测时间；不含评分/报告序列化，不冒充模型或生产端到端延迟。不同家族固定时点在逐 case 输入保存，suite fixed_at=null，不伪造统一业务时点。
- 每条 Check.evidence 都引用该例 observation 的路径、原字节 SHA256、case_run_id、JSON pointer 和 scorer_rule_version。run-index 串联 case/input/trace/manifest/丰富版本摘要，完整报告可从观测逐例重算。

## 审查、隔离、限制与回滚

独立代码审查实际发现 3 项 Important：安全依赖缺失仍通过、畸形结果导致崩溃、原生结构合同过宽。父窗口另独立发现观测到评分因果与原生 trace payload 校验问题，均由上述实际 RED 测试复现并修复。独立复审曾实测 **20 passed**，结论无剩余 Critical/Important；最终新增模型 step 检查后，独立复审实际运行 **21 passed**，确认逐条匹配 step/attempt_id/error/usage，指定真实产物 verify_run valid=true，无剩余 Critical/Important。

所有测试离线、无 PG/真实模型/云/部署。集成测试设置 OTLP 环境并将 socket.connect 设为若触发即失败的哨兵，真实原生路径仍完成。JsonlTrace 显式使用本地 exporter，不读取环境启用 HTTP 导出。每例独立内存状态；start 仅建立合成基线，核验后 owner 的 get/history 内容与数量完全不变，不声称整个运行没有内存初始化写入。只读固定根内夹具，夹具源、E1 历史报告和旧业务文件不修改。

限制：工具失败是 reader 级显式 OSError 注入，模型是 scripted 协议替身，不代表真实模型抗注入质量；K1 是纯治理 API，不代表真实发布存储/检索/撤回传播或最终文本证据支持。review_status=approved 是合成策略输入，非领域人工签字。SHA256 与 verify_run 用于完整性/因果复核，不是针对可信宿主恶意全量重写所有观测与摘要的认证。

未 stage/commit、未切分支、未创建额外聊天，未回退并发修改。回滚只移除本包新增 runner 源码/测试/runner-v1 输入及 runner-results 目录，并将自有 evaluate_enterprise.py 撤回本包新增分支（保留 E1 --bundle/--legacy-materials）；先备份运行证据。不得整体 reset/clean/restore，不得删共享 engineering-20261116 目录，不触及任何知识/工具窗口文件。

## 最终源码及产物摘要

- `src/anlan/evaluation/runner_contracts.py`：`d790a16517ba69df508ffa739ae9a039be76fa1c91149bc76f05dd4acc932d69`
- `src/anlan/evaluation/offline_fixtures.py`：`266cf5bca0d5b75758c962875051a9bf4cca4f57998cc6276f952e1c0006d4e0`
- `src/anlan/evaluation/runner.py`：`da8f7d64c0e055799f64e3e4f75cad667f45fb5ca996072381020416b3dbc433`
- `src/anlan/evaluation/scoring.py`：`b028f4366a249d483b710630c9eeaf39ff92edc0e9786de7cc3bd3457e8c3c38`
- `src/anlan/evaluation/runner_verification.py`：`5e1e61c0b558156beede0f424b81d7d9d3ab53ec6213e10bcb0e3fe5fec9782a`
- `evals/evaluate_enterprise.py`：`da0a70a973f671a51e626ff4341691f62fed092e7bdca0bd45704d9bfbdb174a`
- `tests/test_enterprise_evaluation_runner.py`：`86846025772f70224cf56d933e732e763752a5258ffe0b0adbb6a6e36b512cda`
- `evals/enterprise-eval-v2/runner-results/123a7fc5-343f-48f6-9aad-629ed41f2138/run-index.json`：`b8ae1663e9981788917fe530988d596f0492e4d4a56abae949cf99791cd33158`
- `evals/enterprise-eval-v2/runner-results/123a7fc5-343f-48f6-9aad-629ed41f2138/bundle.json`：`eb96238e1a0c7166fd3cdce8093dbab3850a66bea11e513bcef28a9cdb471fc7`
- `evals/enterprise-eval-v2/runner-results/123a7fc5-343f-48f6-9aad-629ed41f2138/report.json`：`4c41fa49b56d5ca2158cb7fa970bbab0a8f1df73eeb114ec448d4cd6e76901fa`
