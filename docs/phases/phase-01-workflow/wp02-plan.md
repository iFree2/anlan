# WP02：PostgreSQL 持久化与恢复

2026-09-18。用户要求继续下一轮、不再停留于断言练习；练习与真实模型仍待验证，但不阻塞本工作包。遵循已确定的 P1/WP02 方向，采用 writing-plans / TDD 流程，在当前仓库推进，不创建新阶段任务。

冷启动：当前工作流 smoke 12 passed；保留本人修改的追问、AI 补充断言、学习文档与 .idea。系统 PostgreSQL 10.4 不作为本包依赖；从 PostgreSQL 官网链接的 EDB 二进制档案准备独立 PG17，端口 55432、仅 localhost、合成数据，不改变已有服务。中文路径出现真实初始化错误后，数据库运行文件改放 LocalAppData 的独立英文路径。官方 Python 包兼容性经 PyPI / Psycopg 文档和本地源码核对，uv.lock 锁定。

业务目标：新建待补充任务→退出进程→读取原状态→按版本补充→重复请求不重复执行→进程间继续直至待人工复核。身份不匹配仍拒绝。模型/RAG/长期 Memory/多 Agent/服务端门户不在本包范围。

## 最小设计与取舍

- 官方 AsyncPostgresSaver 持有图状态；服务的任务归属与提交记录另存 PostgreSQL。同数据库独立 `anlan_v2` schema，版本化 DDL；初始输入是恢复种子，不是第二份可变状态。
- 任务元数据保存 tenant/user/thread/mode/contract_version。模拟身份从 CLI 入口注入，不从材料/模型读取；这不是生产鉴权。
- 每次提交先保存稳定 request_id/run_id、expected_revision、补充载荷；完成后保存返回快照。相同请求同载荷返回原结果，不再次调用分析器；同 request_id 不同载荷拒绝。
- 使用任务级 PostgreSQL advisory lock 防止多个进程同时恢复同一任务；争用立即返回 busy。单连接内另串行化调用，避免 advisory lock 重入。锁与 saver 必须同连接，丢锁后旧执行不能经第二条连接继续写回。
- 提交记录与 checkpoint 不能原子提交；显式保留 pending 记录，recover 根据 checkpoint 的 run_id/revision/下一节点恢复。新问题未进入 checkpoint 时重用原补充命令；已合并材料后继续剩余节点，不重复加版本。若模型已调用但结果尚未保存，恢复可能再调用模型；不宣称 exactly-once 或跨进程费用限额。
- `start/show/resume/recover/history/db-init` 使用持久化 CLI。原 demo/chat 的内存模式保持可用。持久化模式续接不得偷偷切换分析器模式；当前实测全部 offline，无付费模型调用。
- 数据库故障用可读分类错误呈现，不输出含 DSN/密码的异常；checkpointer 使用受限反序列化。Windows 异步入口使用 SelectorEventLoop。

## 实施与验证步骤

- [x] 锁定 postgres saver / psycopg 依赖，启动隔离 PG，准备本地开发脚本与明确来源记录。
- [x] 先写存储/服务行为测试：旧行为、重复请求、冲突请求、过期版本、pending 恢复；观察失败后实现轻量 registry 和服务入口。
- [x] 官方 saver 可注入 Graph；持久化 registry 支持身份过滤、任务锁、提交记录与 schema 版本；测试真实数据库连接重建、身份隔离及两个进程竞争。
- [x] 增加 CLI 子命令、合成输入文件；进程 A start，B show，C resume，D 复用 request_id；验证状态/版本/run_id 与字段。
- [x] 注入中途失败：先合并后分析失败，再重启 recover；补充不重复，run_id 可关联提交记录。故障前模型执行的外部副作用不能由本包保证 exactly-once。
- [x] 跑适量回归与真实 PG 集成测试，保留命令/快照证据；更新状态、架构、能力、学习记录和 WP02 handoff。本阶段其余验收未通过项继续待验，不创建 P2。

验收：跨进程正常恢复；相同请求不重复生效、不同载荷冲突；过期/越权无修改；进程间争用不双写；故障后版本与输入保留；原12项工作流行为不回退。只对当前小增量声明完成，不以数据库集成测试证明模型效果。

工程验证与交接见 [WP02 handoff](wp02-handoff.md)。清单完成只表示本包工程交付，不表示个人掌握或P1阶段验收通过。
