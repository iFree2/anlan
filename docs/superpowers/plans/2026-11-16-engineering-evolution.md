# 四项工程演进实施计划

> For agentic workers: 使用 test-driven-development，按以下小增量执行，主窗口统一审查集成。蓝图见 ../specs/2026-11-16-engineering-evolution-design.md。

**Goal:** 先闭环工具底座、评测合同、知识 IR、MCP 合同，再沿蓝图推进完整工程。
**Architecture:** 增量版本合同；可信宿主授权；本地统一执行；保留全部旧入口与证据。
**Tech Stack:** Python 3.13、Pydantic v2、pytest、现有 MCP SDK/PG。

## 当前里程碑

- [x] A 基线审计与原改动 hash 保护；55 passed/5 skipped。
- [x] B/C 总蓝图、详细设计、威胁模型与回滚。
- [x] D 独立设计审查；四项修订已落实，见蓝图与各包报告。
- [x] E 发布三个窗口任务所有权，1/4 同窗口串行。
- [x] T1：先写 Registry 重复/目录一致、policy 越权、executor 参数/结果/超时/取消测试并观察 RED，再实现 registry/policy/executor/builtin。迁移 tool_loop 与模型 schemas，运行 `uv run --no-sync pytest -q tests/test_tool_registry.py tests/test_tool_loop.py tests/test_tool_model.py tests/test_knowledge_tool_loop.py tests/test_business_bridge.py`（新增测试文件名可在包报告明确修订）。旧返回不变，未授权处理器调用数为零。
- [x] E1：先写严格清单、独立阻断、未知不通过、人工 pending、版本兼容/历史不改写测试并观察 RED；实现独立评测包/CLI与一个版本化离线报告；运行 `uv run --no-sync pytest -q tests/test_enterprise_evaluation.py`，新增文件名以包报告为准。不得生成假人工金标或未见集。
- [x] K1：先写定位/源文、权限/时效/发布/撤回与回滚不复活测试并观察 RED；实现 DocumentIR 与纯治理，运行 `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py`。旧知识链不变。
- [x] M1（T1 后同窗口串行）：先写注册/能力/证据、来源完整性与宿主字段隔离测试；实现 dynamic_mcp 独立合同及合成配置，不提前开放业务注册执行。运行 `uv run --no-sync pytest -q tests/test_dynamic_mcp_contracts.py`。
- [x] H：独立审查本轮增量，已复现critical/important关闭；最终连续整仓1673 passed/0失败/0错误/0跳过，1 live排除/1第三方警告；Ruff、源码冻结/保护与wheel验证通过。失败与限制在gate-report保留。
- [x] I：状态/架构/能力/学习与2026-11-18最终handoff同步，工程交付、实际质量、本人掌握分开。

## 历史快照与后续里程碑（不得提前标完成）

2026-11-16首轮实施与协调复验：T1/M1、E1、K1已交付；主窗口新增测试集151 passed。原16个dirty文件哈希均未改变。带PG全量基线1050 passed/1 failed（Windows临时文件清理锁）；对应21项复跑通过，保留失败日志；独立空测试库完整回归进行中，不能据定向结果标H通过。

当时第二轮计划为K2a/E2a/M2。2026-11-18当前结果：它们及K3a本地结构检索、M3设备三能力、K3→E1三场景评测已按各自D门禁实施并闭环；完整范围与证据见engineering-20261116/acceptance.md和最终交接。以下为未完成的长期阶段，不据本轮测试勾选：

1. MCP人员/票据端到端、双源/历史时间分工/分页、真实模型选源、企业生产接入及普通对话装配。
2. 授权真实多格式文档、解析与治理持久化/索引发布、真实embedding/重排与质量对照，保持现有知识链兼容。
3. 正式人工评分/60—100审核场景/新未见集、受控基线对照与影子候选发布Gate。领域审核及授权资料缺失时保持未验证，不由AI填补。
4. 每个后续包启动前补充具体代码合同、RED 命令、文件所有权与验收案例；不得凭本总计划一次性重写。
