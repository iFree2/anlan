# WP02 工程验证（2026-09-18）

环境：Windows、Python3.13.3；PostgreSQL17.11（EDB Windows x64），langgraph-checkpoint-postgres3.1.2、psycopg3.3.6，其他锁定版本见根uv.lock。原有PG10.4服务未变；本项目实例只监听127.0.0.1:55432。

| 实际命令 / 行为 | 结果 | 原始证据 |
|---|---|---|
| `uv sync --locked --link-mode copy` | exit0，52个解析包，当前环境可按锁安装 | uv.lock；工具执行记录 |
| `uv run pytest -q --junitxml=docs/phases/phase-01-workflow/evidence/wp02/pytest.xml`（事先加载开发测试DSN） | **45 passed，0 skipped，含11项真实PG测试** | [pytest.xml](pytest.xml) |
| `uv run ruff check .` | All checks passed | 工具执行记录 |
| `uv run python scripts/smoke_postgres.py --output docs/phases/phase-01-workflow/evidence/wp02/cli-smoke.json` | 9个独立CLI进程调用，预期拒绝也核验退出码；SQL查3条完成提交 | [命令/输出/SQL结果](cli-smoke.json)、[轨迹](cli-smoke.trace.jsonl) |
| `scripts/dev-postgres.ps1 -Action Stop` → `-Action Start` → `anlan show` 原task_id | 数据库重启后revision3/awaiting_review与输入保持 | [重启记录](database-restart.log)、[重启后快照](after-database-restart.json) |
| `uv run python scripts/install_postgres.py` | 固定ZIP哈希校验通过，现有独立二进制可复用 | 脚本固定URL/SHA256（本次下载摘要，非供应方签名） |

核心验证：不同进程/连接读取原任务；只修改补充字段；同request_id返回同一快照，不重复调用分析；同ID不同载荷、过期版本、其他tenant/user拒绝；独立进程争用返回busy；pending原始补充保存；分析中os._exit硬退出后恢复run_id/revision不重复；创建时先输出ID，首次硬退出可定位；图完成但提交回执未保存时不重做分析；分析→ask中间退出可补走至interrupt；锁连接断开旧执行无法覆盖新状态；不兼容合同版本不能借缓存绕过。

审查发现并保留的失败路径：

1. 分离的锁/写连接在丢锁后允许旧run覆盖新checkpoint（真实PG回归先失败）；现已共用专用连接。
2. 缓存回执绕过合同版本验证；现查询缓存前校验。
3. 首次失败没有task_id回执，难以从CLI恢复；现归属落库后即向stderr flush回执。

以上三项独立复核通过。另修复Windows中文路径PG初始化UTF8错误，以及Start-Process -Wait误等整个数据库子进程树的问题；开发脚本使用独立英文路径与只等待pg_ctl本身退出。上述全部为AI实现/排错，不记为本人独立掌握。

本轮全部为SYNTHETIC/offline。真实模型请求0、真实token/费用0（无调用）；Schema/恢复测试不证明模型语义效果。未验证生产认证、模型调用exactly-once、跨进程预算、业务写工具、长期Memory、全新机器的完整安装、生产数据库运维或SLA。未配置测试DSN时PG测试会明确skip，不能计作通过。
