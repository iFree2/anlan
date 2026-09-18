# 当前状态（唯一入口）

- 项目：安澜 2.0；当前 P1 多轮工作流，第 1—2 周，未过 Gate。
- 当前工作包：**WP02 PostgreSQL 持久化，工程验收通过**；本人理解/实践待验证，P1 尚未过 Gate。用户明确要求继续推进，练习不再作为编码前置条件。
- 冷启动事实：上一工作包 smoke 12 passed；保留本人追问改动与 .idea。分支 `work/phase-01-wp-02`，上一轮本人/协助练习提交 `7c3ead3`。旧项目只读未改；[来源边界](architecture.md#历史资料来源与适用范围)。
- 已实现：LangGraph 材料循环；可选内存或官方 PostgreSQL checkpoint；持久化归属/提交记录、请求去重、版本检查、任务锁、pending 恢复、创建回执、CLI show/resume/recover/history；原规则/模型边界保留。
- 最近验证：2026-09-18，`uv run pytest -q` **45 passed（含11项真实 PostgreSQL 集成）**，ruff通过、锁文件安装通过；9个独立 CLI 命令、SQL查询3条运行记录、数据库重启后 revision=3 仍保留。[WP02 验证证据](phases/phase-01-workflow/evidence/wp02/verification.md)。
- 本机运行：独立 PG17.11 在127.0.0.1:55432，系统PG10未改。新终端先 `scripts/dev-postgres.ps1 -Action Env`；需要停库用同脚本 `-Action Stop`。数据/凭据位置与复现命令见 README，凭据不入 Git。
- 模型效果：未验证。三个离线样本中 001/002 问题集合符合预期，003 歧义漏检保留；这只是规则基线边界，不能算真实模型效果或泛化结论。
- 真实模型阻塞：用户选择 DeepSeek，但尚未提供完整配置路径；本轮真实请求 **0**，本轮真实调用 token/费用为 0（无请求）。适配器的 HTTP 替身测试不等于接通供应商。收到路径后只读加载，最多 3 次合成请求，无重试；运行时报告返回用量，未知保持 null。
- 本人实践：已核对本人追问修改与三轮demo；断言及WP02实现由AI完成，不记作本人掌握。WP02可选恢复演示练习见 [学习记录](learning-log.md)，不阻塞继续开发。
- 下一步主目标：WP03 真实 DeepSeek 三例联调与初始语义结果复核（待配置路径）；不要再扩数据库基础设施。模型/评测与P1剩余验收完成后才做 Phase Gate、新建 P2 任务。
- 范围/限制：内存模式仍重启丢失；PG任务级互斥已验证，但身份是本地模拟、无生产认证或跨进程费用限额。模型结果保存前硬退出可能重复调用；未实现最终任务修订、取消、工具/RAG/长期Memory/多Agent/事件。日志缺口显式显示，不补造。

冷启动读：[产品](product-scope.md)、[路线图/能力表](roadmap.md)、[架构](architecture.md)、[P1计划](phases/phase-01-workflow/plan.md)、[最新WP02交接](phases/phase-01-workflow/wp02-handoff.md)、[ADR002](decisions/002-postgres-recovery.md)、[验收](phases/phase-01-workflow/acceptance.md)。再检查Git、最近提交，跑 `uv run anlan demo`；数据库工作需加载开发Env并运行相应PG测试，未配置DSN的skip不算通过。
