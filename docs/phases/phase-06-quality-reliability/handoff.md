# P6在途交接

持续授权不变：同目录逐包实施/验证/保留失败/文档/提交后自动下一包；阶段工程Gate后再创建同目录GPT-6 Astra/high的P7任务。仅真正范围/破坏/业务副作用/输入/预算阻塞才问一次，独立工作继续。协调已有30分钟自动续接，不重复建；本任务唯一写入者。

## WP01

原Q-P5-001两次invalid_output、0/2、5072token原件保留。发现SYSTEM的notice句号歧义且无完整Schema；改为Pydantic自动生成Schema和精确JSON字面量。此为明确可证伪假设，不是已证明的旧字段根因。安全诊断type/loc将任意额外字段名脱敏，网关外层JSON/信封/超大响应固定错误标识；串行锁内复制、每次重置。严格应用验证/报警/预算归属没有放宽。

新增两次真实请求（每类一次）2/2有效，见[evidence/wp01/live-report.md](evidence/wp01/live-report.md)。两链真实PG/BGE/模型候选及模拟反馈/revise/stale完成，后续新revision重核明确替身。Q-P5-001最小候选阻塞关闭，不能宣称泛化/生产/现场/未知场景真实验证或本人掌握。旧0/2与原P2/P3/P4无增益/引用问题/未知根因继续保留。

PG唯一账本累计34/100：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9、P5-WP02=4。32 succeeded、2 failed、0 reserved。相同感知问题仍用P5-WP02，不能换阶段重置。新授权累计65109输入/8550输出/73659总token，P1历史3次1184另列，金额未查。本包实际实验当前进程只读既有docs/DS.txt且不输出，子CLI不继承模型凭据。

红绿与独立只读审查见[verification](evidence/wp01/verification.md)，最终CI状态以ci-final.json为准。本包只改网关诊断/感知提示，未修改业务PG状态与锁边界。原P5 Gate/清洁wheel是旧版本证据，不用旧wheel冒充本次源码。

## 接续

下一包[WP02](wp02-plan.md)：显式来源/SHA与合成反馈、Badcase、开发/留出冻结、只读查看/录制回放/真实复跑隔离。WP03有限Judge与单多复测，WP04真实故障/并发/延迟及SQL分析，均按主plan范围细化。P6阶段Gate尚未通过。

用户16路径32行中文译文仍保留，.idea不动。learning-log继续P1→P5原排序后新增P6入口和WP01条目，完整文件不提交；本次原始备份.runtime/p6-wp01/learning-log-before.md可逐字节验证。独立wp01-learning.md可提交。原用户变化映射与P5交接保护要求继续有效。

新shell先scripts/dev-postgres.ps1 -Action Env，PG17.11在127.0.0.1:55432；不碰系统PG10。无Docker/Compose/远程CI事实不变。实际模型端点/模型/20秒/1024输出token/无重试与合成数据约束继续。
