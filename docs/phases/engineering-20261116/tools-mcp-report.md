# T1 / M1 独占包实施记录

## 接口与测试小计划（实施前）

T1：ToolDefinition(name, description, input_model, output_model, handler, clock, object_field)；Registry 拒绝重复并生成 schemas；Policy 根据可信 identity、refs、显式 knowledge_question 冻结 TaskCatalog。Executor 每次验证目录成员、严格输入及预期参数，限制 4096 字节输入/64KiB 输出、5 秒，取消传播、异常分类；校验结果 tool/object_id/宿主时钟区间，合同错误 evidence_valid=False。DeepSeek.bind_catalog 返回新绑定对象，保留 next(messages, run_id) 与旧 fake；循环保留旧报告/预算/trace/citation。

RED 用例：重复、授权 schema 一致、共享模型隔离；越界/伪造身份零调用；错误类型/工具/对象/时点、异常、超时、取消和大小；原 scripted/知识与 HTTP/MCP/Java 回归。

M1（T1 后）：独立 v1 能力、注册清单、可信连接声明、三场景类型化载荷及分页/来源合同；remote 与 host 分层且拒绝宿主字段注入；合成配置只作合同样例，无管理或 runtime。测试缺字段/版本/状态/时区/分页/来源/元数据隔离。

## 实际实现文件

- `src/anlan/tools/registry.py`：不可变定义、重复检测、schema 单一来源。
- `policy.py`：宿主身份与 refs/显式知识问题形成冻结 TaskCatalog；模型不能传入身份。
- `executor.py`：参数/授权/执行/输出合同边界，4096 UTF-8 输入字节、64KiB 输出、5 秒单次上限，父循环限额仍在旧工作流。
- `builtin.py`：人员/区域/知识完整迁移适配；固定 ToolResult 未修改、未扩成任意 dict。
- `src/anlan/workflows/tool_loop.py`：移除内嵌 allowed handler 字典，以同一 catalog 绑定模型与 executor；保留报告版本、model/tool 计数、账本预占、trace、来源与引用。新增 evidence_valid 区分实际执行与通过合同绑定的观察，错误工具/对象/时点绝不进入最终引用集合。
- `src/anlan/llm/tool_model.py`：默认 schemas 复用 builtin；bind_catalog 创建独立模型视图与独立 gateway 运行状态，共享原 config/client/ledger/work_package。保留旧 next(messages, run_id)、scripted/fake。
- `src/anlan/tools/dynamic_mcp/{__init__,contracts}.py`、`README.md`、`examples/{equipment,contractor-person,permit}.json`：M1 八能力、请求/返回/注册声明、来源/分页/有效期、宿主 receipt 独立层及三个合成配置。无 runtime/管理装配。
- 新增 `tests/test_tool_registry.py`、`test_tool_executor.py`、`test_dynamic_mcp_contracts.py`。

## 实际 RED / GREEN

1. `uv run --no-sync pytest -q tests/test_tool_registry.py tests/test_tool_executor.py`：RED **10 failed**（缺 registry/executor 与 bind_catalog）。实现后与旧回归合跑首轮 60 passed / 2 failed：旧知识替身无 clock，知识失败的 now 与事实固定 clock 不一致；通过只读 adapter 统一可信时钟，未修改旧测试。
2. T1 定向 `tests/test_tool_registry.py tests/test_tool_executor.py tests/test_tools.py tests/test_tool_loop.py tests/test_tool_model.py tests/test_knowledge_tool_loop.py tests/test_business_bridge.py`：**80 passed in 43.85s**。
3. `uv run --no-sync pytest -q tests/test_dynamic_mcp_contracts.py`：初次 RED **11 failed**（缺 dynamic_mcp 合同）；初次 GREEN **11 passed in 0.52s**。
4. 新增业务有效期与可信 argv profile 测试：RED 中 expired_record 显示 usable=True；修复后 GREEN。argv 测试首次含 Windows 默认编码错误，改为显式 UTF-8 后重跑 RED，确认 TypeError（缺 stdio_argv），再实现精确受信 argv profile 检查。
5. 独立审查要求修复 shared gateway：并发测试 RED 在 B 的首调用错误 budget_exceeded（A 已占共享计数）；改为每绑定新建 gateway、共享真实 ledger，GREEN。测试同时断言 A/B 的 attempt 1/2 正确归属及每任务预算上限。
6. 新增 training scope RED：**1 failed, 23 passed**，异厂培训未抛错；增加厂区合同校验后新模块集 **37 passed in 1.61s**。
7. 中间完整定向集 **106 passed in 50.12s**；最终命令/结果见下。

## 审查与约束

- 落实审查：同一 TaskCatalog 显式给模型/Executor；绝不就地改共享 model schemas；旧 next/fake 可用；gateway 的计数/last_attempt_id 不跨任务共享。
- 结果经 JSON 重验（不信 model_copy 绕过校验），校验 tool/object_id/可信 clock 前后区间。固定时钟等价精确相等；实时钟允许本次执行区间。不合规结果 data_error、evidence_valid=False。未知/业务错误仍是有效观察，不能改写成安全结论。
- 取消传播 CancelledError；超时单独 timeout；未授权 executed=False 且处理器次数为零。异常不泄漏 secret sentinel。
- 独立审查由集成窗口已反馈 T1 important 并已修复；M1 仍需集成窗口独立复验，不声称完整 H 门禁已通过。
- 全库 Ruff 曾观察其他窗口的 `evaluation/adapters.py`、`evaluation/report.py` 三项 E501；没有修改其所有权文件。自有范围 Ruff 已通过。最终全库状态由主窗口统一复验。

## 限制与回滚

首轮仅 T1/M1。没有实现 MCP 管理身份认证、持久化、连接/发现/SDK runtime、来源竞争选源、动态模型执行、真实企业服务或三场景端到端。配置 state 与 ENTERPRISE_DECLARED 是声明，不代表授权或来源认证。usable 仅为结构/来源完整观察，不是无风险判定。Pydantic 交叉字段规则必须实际运行，不能只依赖导出的 JSON Schema。

本窗口零真实模型调用、零部署、无云操作，无 SQL 修改、无 stage/commit/分支/额外窗口。原脏文件、总状态/roadmap/架构/能力/学习文档未修改。其他窗口并发新增文件未回退。

回滚仅人工撤销本包两个 tracked 文件中的自有变更（tool_loop.py / tool_model.py），确认无他人后续编辑后移除本包新增 registry/policy/executor/builtin、dynamic_mcp、三个测试；保留本报告。禁止 reset/clean 或整工作树恢复；不触碰旧 ToolResult/HTTP/MCP 绑定防线及其他窗口文件。无需数据库回滚。

## 最终审查补充修复（集成窗口反馈）

- M1 时间绑定 important 已实际复现 RED：票据/交叉作业 2020 窗口、与请求恰好相接的两种边界，以及未来故障观察，共 **7 failed, 24 passed**。现在 Ticket/Overlap 必须与 coverage 有严格正长度交集；原票据窗口可扩出请求窗口，不能只因未完全包含而拒绝。Fault.observed_at 晚于 queried_at 拒绝。
- M1 元数据空白 important 已实际复现 RED：EvidenceSource.version / HostReceipt.selection_reason 纯空白均被接受，**2 failed, 31 deselected**。现在元数据 Text strip 后要求非空；original_status 独立保留原文且要求含非空白字符。
- 修复后新增模块集 `uv run --no-sync pytest -q tests/test_tool_registry.py tests/test_tool_executor.py tests/test_dynamic_mcp_contracts.py` → **46 passed in 2.78s**。随后补充两种“票据原窗口延伸出请求窗口但真实相交”的正例，最终完整定向集见后。
- 自有全部 Python/测试范围 `uv run --no-sync ruff check ...` → **All checks passed!**；`git diff --check` 无输出，exit 0。

## 最终完整定向命令

```powershell
uv run --no-sync pytest -q tests/test_tools.py tests/test_tool_registry.py tests/test_tool_executor.py tests/test_dynamic_mcp_contracts.py tests/test_tool_loop.py tests/test_tool_model.py tests/test_knowledge_tool_loop.py tests/test_business_bridge.py
```

审查补充前此命令实得 **107 passed in 70.97s**，无 skipped。包含真实本地 Java HTTP 及官方 MCP SDK stdio 握手/调用/权限/取消等 business_bridge 测试，不能混称动态 M1 runtime 验收。新增补充修复后的结果追加如下。

最终增补后结果：**118 passed in 54.94s**，exit 0，无 skipped / warnings；本包新增 48 项测试、既有定向 70 项均通过。

最终全库 `uv run --no-sync ruff check src tests scripts evals` → **All checks passed!**，exit 0（其他窗口在并发期间已修复其 lint）。本窗口仍仅修改自有范围。

T1/M1 首轮可审查增量已完成；全量非 live、PG 环境恢复、其余 K/E 包集成与最终 H 门禁由主窗口负责，本报告不将其代签通过。后续等待集成窗口决定下一包，不扩展 M2/M3 runtime。
