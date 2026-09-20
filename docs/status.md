# 当前状态（唯一入口）

- 项目：安澜 2.0；当前 P1 多轮工作流，第 1—2 周，未过 Gate。
- 当前工作包：**WP03 三例真实模型联调已完成**；P1 尚待阶段冻结评测与收尾Gate，个人掌握独立待验。用户要求持续开发、AI先运行验证、先列阶段掌握清单；不以完成练习阻塞编码。
- 冷启动事实：2026-09-20从bd91454读取仓库，保留14个文件的既有中文注释修改与.idea；模型/评测smoke16 passed。当前分支 `work/phase-01-wp-03`。旧项目只读未改；[来源边界](architecture.md#历史资料来源与适用范围)。
- 已实现：LangGraph 材料循环；可选内存或官方 PostgreSQL checkpoint；持久化归属/提交记录、请求去重、版本检查、任务锁、pending 恢复、创建回执、CLI show/resume/recover/history；原规则/模型边界保留。
- 最近验证：2026-09-20全量 **50 passed、0 skipped（含11项真实PG集成）**，ruff通过。WP03修正评测mode透传、补配置/用量完整性汇总与缺配置不留空文件；新增失败回溯脱敏回归。[原始测试记录](phases/phase-01-workflow/evidence/wp03/pytest.xml) / [实验报告](phases/phase-01-workflow/evidence/wp03/final-report.md)。WP02的PG恢复证据继续有效，未重建模块。
- 本机运行：独立 PG17.11 在127.0.0.1:55432，系统PG10未改。新终端先 `scripts/dev-postgres.ps1 -Action Env`；需要停库用同脚本 `-Action Stop`。数据/凭据位置与复现命令见 README，凭据不入 Git。
- 模型效果：3次真实DeepSeek请求均返回合法候选；最终问题集合3/3符合三个已见开发样本，TP2含规则/模型各1条。离线同集2/3。只证明小样本联通与行为，未证明泛化或复杂风险研判。
- 配置/用量：用户已指定 `docs/DS.txt`，只读加载，已加入Git忽略且不输出密钥。本包调用3次，无重试，输入1126/输出58/总1184 token，用量完整；实际扣费未查询。3次额度已用完，不重复调用覆盖结果。
- 本人实践：已核对本人追问修改与三轮demo；断言及WP02实现由AI完成，不记作本人掌握。WP02可选恢复演示练习见 [学习记录](learning-log.md)，不阻塞继续开发。
- 下一步主目标：P1收尾，制定并冻结阶段回归集、核对剩余工程验收，再决定Phase Gate与P2任务；下一真实实验另明确样本及请求上限。各阶段个人要求见roadmap，个人掌握待验不阻塞编码，不虚报达成。
- 范围/限制：内存模式仍重启丢失；PG任务级互斥已验证，但身份是本地模拟、无生产认证或跨进程费用限额。模型结果保存前硬退出可能重复调用；未实现最终任务修订、取消、工具/RAG/长期Memory/多Agent/事件。日志缺口显式显示，不补造。

冷启动读：[产品](product-scope.md)、[路线图/阶段掌握要求](roadmap.md)、[架构](architecture.md)、[P1计划](phases/phase-01-workflow/plan.md)、[最新WP03交接](phases/phase-01-workflow/wp03-handoff.md)、[ADR002](decisions/002-postgres-recovery.md)、[验收](phases/phase-01-workflow/acceptance.md)。再检查Git与对应smoke；PG测试先检查/启动项目实例，再加载Env，skip不算通过。当前本地开发库密码已轮换，旧终端需重新执行Env脚本。
