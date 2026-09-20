# 当前状态（唯一入口）

- 项目：安澜 2.0；**P1多轮工作流工程Gate已通过，P2受控工具与知识入口就绪**。个人掌握独立待验，未因工程通过自动升级。
- 当前工作包：WP04阶段冻结回归与P1交接完成；后续在同目录新P2任务冷启动，首先确认P2-WP01两个只读合成事实工具。用户要求AI先运行验证，学习项先列出且不阻塞编码。
- 冷启动事实：本包基于1788fdb，工作流/评测smoke17 passed；保留14个文件既有中文注释改动与.idea。当前分支 `work/phase-01-wp-04`。旧项目只读未改；[来源边界](architecture.md#历史资料来源与适用范围)。
- 已实现：LangGraph 材料循环；可选内存或官方 PostgreSQL checkpoint；持久化归属/提交记录、请求去重、版本检查、任务锁、pending 恢复、创建回执、CLI show/resume/recover/history；原规则/模型边界保留。
- 最近验证：2026-09-20全量 **56 passed、0 skipped（含11项真实PG）**，ruff/锁文件同步通过；冻结工程回归8例/25步骤、9命令跨进程PG演示通过。历史3例预测本地重评分相符，本包新模型请求0。[P1 Gate及最终证据](phases/phase-01-workflow/evidence/wp04/gate-report.md)。
- 本机运行：独立 PG17.11 在127.0.0.1:55432，系统PG10未改。新终端先 `scripts/dev-postgres.ps1 -Action Env`；需要停库用同脚本 `-Action Stop`。数据/凭据位置与复现命令见 README，凭据不入 Git。
- 模型效果：3次真实DeepSeek请求均返回合法候选；最终问题集合3/3符合三个已见开发样本，TP2含规则/模型各1条。离线同集2/3。只证明小样本联通与行为，未证明泛化或复杂风险研判。
- 配置/用量：用户已指定 `docs/DS.txt`，只读加载，已加入Git忽略且不输出密钥。本包调用3次，无重试，输入1126/输出58/总1184 token，用量完整；实际扣费未查询。3次额度已用完，不重复调用覆盖结果。
- 本人实践：已核对本人追问修改与三轮demo；断言及WP02实现由AI完成，不记作本人掌握。WP02可选恢复演示练习见 [学习记录](learning-log.md)，不阻塞继续开发。
- 下一步主目标：P2-WP01人员资质/区域状态两个实际读取合成记录的只读工具，带来源/时效/未知及错误，先固定路由。新任务模型GPT-6 Astra/high，先按仓库冷启动确认范围；不重做P1或新增多Agent。该首包无需模型调用。
- 范围/限制：内存模式仍重启丢失；PG任务级互斥已验证，但身份是本地模拟、无生产认证或跨进程费用限额。模型结果保存前硬退出可能重复调用；未实现最终任务修订、取消、工具/RAG/长期Memory/多Agent/事件。日志缺口显式显示，不补造。

下一任务冷启动读：[产品](product-scope.md)、[路线图](roadmap.md)、[P1阶段handoff](phases/phase-01-workflow/handoff.md)、[P2 plan](phases/phase-02-tools-rag/plan.md)、[P2 acceptance](phases/phase-02-tools-rag/acceptance.md)、必要[ADR002](decisions/002-postgres-recovery.md)。检查Git/最近提交与最小smoke。PG测试先确认实例运行并加载Env，skip不算通过；不要输出凭据或从历史调用额度推导新授权。
