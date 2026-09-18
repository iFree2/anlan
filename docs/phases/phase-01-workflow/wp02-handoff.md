# WP02 交接：PostgreSQL 持久化工程已验，本人掌握待验证

目标与交付：材料任务退出进程后可找回、补充和恢复。官方 AsyncPostgresSaver 保存Graph状态；PostgresRegistry保存归属/创建种子/提交回执。稳定request_id+revision处理重复与过期，task级锁与同连接写入阻止争用和丢锁后旧写；recover续接pending而不重复合并材料。尚未实现最终任务修改或取消。

入口：README 的 PostgreSQL 演示；本机已经安装独立PG17.11且当前运行于127.0.0.1:55432。新终端 `scripts/dev-postgres.ps1 -Action Env`；未运行则用 `-Action Start`；停库用`-Action Stop`。数据位于LocalAppData/Anlan2Runtime/postgres-17.11/anlan2-data，开发密码在忽略的.runtime/postgres-dev/connection.json，不能输出/提交。系统PG10服务未变。依赖`uv sync --locked --link-mode copy`。

关键文件：`src/anlan/service.py`（幂等与恢复），`registry.py`（合同/内存），`postgres.py`（SQL及官方saver），`sql/001_registry.sql`（迁移v1），`workflow.py`（原图），`cli.py`（start/show/resume/recover/history/db-init）。开发环境脚本在scripts，合成补充文件在examples/synthetic，测试在tests/test_recovery.py和test_postgres.py；不把所有内容塞入src。

验证：[原始证据及说明](evidence/wp02/verification.md)。45项全部通过（含11项真实PG），ruff通过。9次CLI进程、SQL记录、数据库重启快照均保存。测试中有进程硬退出、丢锁连接、丢完成回执、分析/interrupt边界；审查3项问题先复现再修复并复核。

重要决定：[ADR002](../../decisions/002-postgres-recovery.md)。checkpoint与提交记录不是单一原子事务；保存pending并显式恢复。模型可能在结果落库前硬退出后重复调用；不宣称exactly-once或全账户预算。CLI身份参数仅本地模拟，不能作为生产认证。初始task_id回执在分析前输出stderr，stdout仍是最终JSON。

版本：状态合同material-state-v1，数据库迁移001，Prompt仍materials-v1，开发数据仍materials-v1-dev-seen；本包真实模型请求0。本人此前修改追问属本人证据，断言与本包代码/测试由AI完成；新练习和3个理解问题在learning-log待验证。用户已授权继续，不以完成练习阻塞下一工作包。

下一主要目标：WP03真实DeepSeek三例联调，等待用户指定配置路径，不去扫描无关凭据。读取status、P1计划、本交接及ADR；检查Git和最小smoke后，仅完成三次受限调用、用量与语义复核。不要重建数据库模块，不把PG工程通过当P1阶段Gate通过，不提前新建P2任务。原始冻结留出集与P1剩余模型/学习验收保持待验。
