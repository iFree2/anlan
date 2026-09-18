# 当前状态（唯一入口）

- 项目：安澜 2.0；当前 P1 多轮工作流，第 1—2 周，未过 Gate。
- 当前工作包：WP01 内存工作流与可选模型；**离线工程部分已交付，真实模型与本人练习待验证**，工作包仍进行中。
- 冷启动事实：2026-09-17 新目录为空，无适用 AGENTS/Git/现有 smoke；现在分支 `work/phase-01-wp-01`。旧项目只读，未复制或修改；[历史参考来源及边界](architecture.md#历史资料来源与适用范围)。
- 已实现：真实 LangGraph 状态/条件边/interrupt/resume，CLI 两轮局部补充、版本及归属校验；规则/模型区分，DeepSeek 异步适配器，最小 JSONL 轨迹与三个已见开发评测样本。
- 最近验证：Python 3.13.3；`uv sync --locked --link-mode copy` 成功；`uv run pytest -q` **29 passed**；`uv run ruff check .` 通过；`uv run anlan demo` 显示 revision 1→2→3、最后 awaiting_review。命令、XML 和样本结果见 [验证证据](phases/phase-01-workflow/evidence/wp01/verification.md)。
- 模型效果：未验证。三个离线样本中 001/002 问题集合符合预期，003 歧义漏检保留；这只是规则基线边界，不能算真实模型效果或泛化结论。
- 真实模型阻塞：用户选择 DeepSeek，但尚未提供完整配置路径；本轮真实请求 **0**，本轮真实调用 token/费用为 0（无请求）。适配器的 HTTP 替身测试不等于接通供应商。收到路径后只读加载，最多 3 次合成请求，无重试；运行时报告返回用量，未知保持 null。
- 本人实践：已核对本人修改追问及三轮 demo 输出；随后按本人要求由 AI 补内容断言。2026-09-18 工作流测试 12 passed、对应 ruff 通过；断言与字段合并的本人理解仍待验，详见 [学习记录](learning-log.md)。
- 下一步：按本人节奏阅读新增断言、讲解字段合并；配置到位后完成不超过 3 次真实开发样本调用。随后按用户指示启动 WP02 PostgreSQL 恢复，不自动跳过学习验收。
- 范围/限制：内存 checkpoint 与归属索引重启丢失；单进程顺序调用；模拟身份非生产认证；未实现工具循环、RAG、长期记忆、多 Agent 或事件。日志失败会显示 trace_warning，轨迹缺口不补造。

冷启动按顺序读：[产品](product-scope.md)、[路线图及能力表入口](roadmap.md)、[架构](architecture.md)、[P1 计划](phases/phase-01-workflow/plan.md)、[WP01 交接](phases/phase-01-workflow/wp01-handoff.md)、[ADR001](decisions/001-workflow-state.md)、[验收](phases/phase-01-workflow/acceptance.md)。再检查 Git 状态/最近提交，运行 `uv run anlan demo` 与对应最小测试；以代码/测试/评测结果纠正文档。尚未到创建 P2 任务的时点。
