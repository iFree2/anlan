# P1：多轮材料工作流（历史阶段计划）

2026-09-20工程Gate通过；个人掌握仍待验证，语义泛化未验证。当前状态由docs/status.md维护，完整交接见 [handoff](handoff.md)，阶段结论见 [Gate报告](evidence/wp04/gate-report.md)。

初始目标：先看清材料分析→追问→补充→再分析的状态变化，再实现PostgreSQL跨进程恢复；限CLI、合成数据和受限模型，无审批/真实控制。本阶段保持LangGraph外层状态权威，未创建多Agent壳。

| 工作包 | 实际范围 | 计划/交接及证据 |
|---|---|---|
| WP01 | 内存Graph、四字段合同、规则/模型边界、CLI与基础轨迹 | [交接](wp01-handoff.md)、[验证](evidence/wp01/verification.md)、[ADR001](../../decisions/001-workflow-state.md) |
| WP02 | 官方PG saver、归属/提交、版本/幂等、跨进程/故障恢复 | [计划](wp02-plan.md)、[交接](wp02-handoff.md)、[ADR002](../../decisions/002-postgres-recovery.md) |
| WP03 | 三例真实联调、模式标记/用量完整性、错误回溯脱敏 | [计划](wp03-plan.md)、[交接](wp03-handoff.md)、[报告](evidence/wp03/final-report.md) |
| WP04 | 八例冻结工程回归、历史预测重评分、阶段Gate及P2启动准备 | [计划](wp04-plan.md)、[阶段交接](handoff.md)、[最终Gate](evidence/wp04/gate-report.md) |

已采用取舍：内存起步后接PG，不经SQLite；模型分析与interrupt分节点；生命周期由代码控制；归属/提交/checkpoint边界见ADR；模拟身份非生产认证。完整原始规划可查Git历史，不再在已结束阶段主计划重复当前状态。

本人练习按用户节奏补齐，不作为继续编码前置。保留所有实验结果，不将已见回归当独立holdout。下一阶段从 [P2计划](../phase-02-tools-rag/plan.md) 冷启动，不重做P1已验证实现。
