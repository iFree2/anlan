# ADR002：checkpoint 与提交记录配合恢复

日期：2026-09-18。采用，服务于 P1-WP02；细节见 [工作包计划](../phases/phase-01-workflow/wp02-plan.md)。

官方 AsyncPostgresSaver 保存状态，`anlan_tasks` 保存可信归属及初始输入，`anlan_operations` 保存有稳定 ID 的提交和完成快照。二者分别提交，不能声称原子性。每个任务只允许一个 pending operation；PostgreSQL advisory lock 保证一个任务同一时刻由一个服务实例执行。**锁、registry 和 checkpoint 共用同一专用连接**：连接关闭释放锁，同时阻断旧执行的数据库写入。不能将锁与 saver 放在不同连接，否则旧执行丢锁后仍可能覆盖新状态（已由真实数据库回归复现并修正）。

同 request_id、同 expected_revision/字段载荷返回已保存结果；冲突载荷拒绝，缓存返回前也校验合同版本。checkpoint 已含该 run_id 时，不重新合并补充，而检查是否需要继续剩余节点。未含该 run_id 时重用存下的提交。明确 recover 入口处理 pending，普通新提交提示先恢复；读状态不会自动再调用模型。Graph 使用 sync durability，确保节点边界写入完成后才运行下一节点。CLI 在归属持久化后立即输出 task_id 回执，首次执行硬退出后仍可定位恢复。

初始输入是恢复种子，运行期间当前材料只从图 checkpoint 读取。归属索引必须在任何 checkpoint 读取前校验，不以 thread_id 的不可猜测性替代授权。分析器 mode 和状态合同版本持久化，拒绝不兼容模式续接。

保留重复外部模型请求的风险：如果供应商已处理但节点结果未保存，恢复会再次执行节点。当前仅合成、只读分析；未来写工具需独立幂等机制。本包不提供全账户/跨进程预算、生产认证或全局任务队列。

环境采用独立 PG17，因本机中文路径初始化编码失败，二进制/数据保存在 `%LOCALAPPDATA%/Anlan2Runtime/postgres-17.11`；本项目 `.runtime` 保存下载缓存、日志与本地开发凭据。只监听127.0.0.1，不修改已存在 PG10 服务。生产部署、权限账号划分和数据库运维不在本轮。

依据：[官方 PostgreSQL saver](https://pypi.org/project/langgraph-checkpoint-postgres/)（setup、autocommit/dict_row、反序列化限制）、[Psycopg asyncio](https://www.psycopg.org/psycopg3/docs/advanced/async.html)（Windows 事件循环）、[PostgreSQL Windows 下载](https://www.postgresql.org/download/windows/)（EDB ZIP）。
