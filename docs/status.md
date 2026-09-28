# 当前状态（唯一入口）

- 项目：安澜2.0；**P1—P6工程Gate通过，P7待接续；模型泛化、并发读取能力与本人掌握未通过或未验证**。不能随工程状态升级这些结论。
- 当前工作包：P6-WP04及阶段工程Gate通过：最终本地CI434 passed/0 skipped（84真实PG），88安装源码/资源SHA与CI一致，两类清洁HTTP/SSE/重启和原P4/P5冻结回归通过；WP04预算42→42，9月28日恢复项目PG后再次核对仍42。[P6 Gate报告](phases/phase-06-quality-reliability/evidence/wp04/gate-report.md)。同任务并发4/8分别11/13个409的性能失败保留，Judge5/6的一错保留，未以工程Gate冒充全面质量通过。
- 质量项：[Q-P5-001](quality-items.md)最小真实候选阻塞关闭，不能据此宣称现场能力或泛化通过。两例结构/有限语义由AI逐项复核，未知场景仅离线负例、非独立人类金标。[复验报告](phases/phase-06-quality-reliability/evidence/wp01/live-report.md)。
- 持续授权（2026-09-20，用户本任务及项目协调任务同步）：按路线图逐工作包自动实现、验证、保存失败/退化、更新状态/矩阵/学习/交接，再继续下一包；不等待常规范围确认、个人练习或“继续”。阶段工程Gate通过后在同目录创建下一阶段GPT-6 Astra/high任务并以handoff续接。只在明显范围变化、破坏性操作、真实业务副作用、缺少关键输入或用量预算耗尽时暂停依赖部分，可独立工作继续。
- 模型长期执行授权（2026-09-20，协调任务同步用户“长期授权你全力推进”）：采用已告知用户的保守执行上限，每工作包最多10次、新授权后项目累计最多100次，失败尝试也占用；这是我方执行上限而非用户指定金额预算。仅既定供应商/模型、合成数据、有界输入输出/超时/无隐式重试，不扩价位或购买额度。唯一账本为项目PG的model_budget_authorizations/model_budget_attempts，生产授权20260920-long-term-v1，当前累计42/100，P2-WP02=6/10、P2-WP04=6/10、P3-WP03=9/10、P4-WP02=9/10、P5-WP02=4/10、P6-WP03=8/10；40次succeeded、旧2次invalid_output failed，无未完成预占；已知新授权输入70746/输出9844/总80590token。[最新实验与账本快照](phases/phase-06-quality-reliability/evidence/wp03/live-v2.json)。P1历史3次/1184token单独保留；跨进程/子任务共享预占，达上限才再询问。
- 冷启动历史：2026-09-20基于 `fc64b27`，分支 `work/phase-01-wp-04`；冷启动24项smoke（含2项真实PG）、三轮demo和冻结回归通过。既有14文件中文注释与.idea保留，未发现适用AGENTS；[核对记录](phases/phase-02-tools-rag/cold-start.md)。旧项目未读取或修改；[来源边界](architecture.md#历史资料来源与适用范围)。
- 已实现：材料循环/PG恢复、三只读工具/有界模型引用摘要、共享预占、真实本地中文向量/pgvector/知识版本时效撤回；本地Jaeger/OTLP追踪和独立归档导入；PG用户枚举偏好生命周期、上下文预算、版本化指引与单模型综合候选。模型摘要仍是待人工复核候选，不改变原材料或产生批准。
- P1最终验证（历史证据，本轮已核对原始报告）：2026-09-20全量 **56 passed、0 skipped（含11项真实PG）**，ruff/锁文件同步通过；冻结工程回归8例/25步骤、9命令跨进程PG演示通过。历史3例预测本地重评分相符，WP04新模型请求0。[P1 Gate及最终证据](phases/phase-01-workflow/evidence/wp04/gate-report.md)。这是P1冻结时的历史记录，P2最新验证以上述当前工作包证据为准。
- 本机运行：独立 PG17.11 在127.0.0.1:55432，系统PG10未改。新终端先 `scripts/dev-postgres.ps1 -Action Env`；需要停库用同脚本 `-Action Stop`。数据/凭据位置与复现命令见 README，凭据不入 Git。
- P3模型效果：三已见任务×三策略共9请求，应用接受6拒绝3；无/有记忆均2/3接受，有记忆多755token（10.9%），未证明质量收益。去知识原文少token但丢依据；保留错述上下文、离题引用与材料说明无引用类型导致的拒绝。[报告](phases/phase-03-memory-context/evidence/wp03/live-report.md)。P1/P2历史效果见各阶段交接。
- 历史配置/用量：用户指定 `docs/DS.txt`，已Git忽略且不输出密钥。P1-WP03调用3次，无重试，输入1126/输出58/总1184 token；实际扣费未查询。P2-WP01未读取模型凭据、新请求0，不重复历史调用覆盖结果。
- 本人实践：已核对本人追问修改与三轮demo；断言及WP02实现由AI完成，不记作本人掌握。WP02可选恢复演示练习见 [学习记录](learning-log.md)，不阻塞继续开发。
- 下一步主目标：按[P7计划](phases/phase-07-takeover-career/plan.md)同目录接续个人接管材料、有限Memory比较/小任务复用/离线多模态与如实项目表达。先读[P6最终交接](phases/phase-06-quality-reliability/handoff.md)，持续授权不变；新供应商/模型/真实素材不能自行扩授权，独立工作继续。
- 范围/限制：本地模拟身份，非生产认证；Jaeger内存不是恢复/预算权威。P2保留摘要次要主张缺显式引用、混合检索无增益和PG非正常退出原因未明等事实。原始事件/关联、显式材料修订与感知重核已完成；重核持久取消与本地服务已完成，材料通用取消/生产接入未实现；Compose和远程CI未运行；P3记忆仅两类合成偏好，保留审计不是生产隐私删除。WP02长暂停超时根因未定；个人掌握仍待本人证据。

下一任务冷启动读：适用AGENTS、产品/路线图、[P6交接](phases/phase-06-quality-reliability/handoff.md)、[P7 plan](phases/phase-07-takeover-career/plan.md)/acceptance、quality-items与必要ADR。Git/即时PG预算/最小smoke后直接开始首包。原16路径32行译文/.idea及用户学习排序继续保护；P6学习条目附后，整文件仍unstaged。协调任务已有30分钟续接，不重复创建。
