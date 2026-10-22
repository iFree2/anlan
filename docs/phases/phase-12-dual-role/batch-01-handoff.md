# P12 B1 交接：可信角色、合同、权限与协作存储

日期：2026-10-22（Asia/Shanghai）。本批实现提交：`685484421831a550685c84047b77c2919c12240c`（`feat: add trusted dual-role contracts and collaboration storage`）。本交接文档以单独文档提交补充，避免在提交中写入自身哈希。接手时用 `git log -1 -- docs/phases/phase-12-dual-role/batch-01-handoff.md` 查询文档提交。

本会话从当前 local 检出 `1fe1dec` 开始，阅读了已批准的设计、计划和验收清单；方案基线为 `a845274`。只执行 B1，没有创建 worktree/其他会话、派发子代理、SSH、部署或真实模型调用。未修改 HTTP、Graph、会话/任务原权限或前端。此交接不代表 B2 或 P12 全流程通过。

## 文件范围

- 新增 `src/anlan/collaboration/__init__.py`、`contracts.py`、`policy.py`。
- 新增 `src/anlan/infrastructure/collaboration.py`、`src/anlan/sql/017_collaboration.sql`。
- 修改 `src/anlan/interfaces/service_config.py`。
- 新增 `tests/test_collaboration_config.py`、`tests/test_collaboration_policy.py`、`tests/test_collaboration_store.py`。
- 必要相邻修改：`scripts/verify_package_layout.py` 和 `tests/test_package_layout.py`。原脚本遍历全部资源后仍要求固定 9 个资源，实际 wheel 已有 17 个，导致真实离源码校验失败；现逐个检查所有源 SQL/资产的存在及字节一致性，不硬编码总数。回归证明漏掉旧 `001_registry.sql` 或改坏新 SQL017 均被拒绝，未删旧迁移校验。
- 本文档 `docs/phases/phase-12-dual-role/batch-01-handoff.md`。

没有暂存或覆盖用户原有 dirty 路径：`docs/roadmap.md`、`docs/status.md`、`.superpowers/`、`docs/phases/phase-10-dynamic-mcp/`、`tests/test_tool_loop_live.py`。没有使用 `git add -A`。SQL012 保留，既有预算迁移和账本未改。

## RED → GREEN 与实跑证据

1. `.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_config.py`：RED 为 **2 failed, 10 passed**，失败分别为缺少 `TokenGrant.collaboration_role` 和显式角色字段被旧配置拒绝。拒绝矛盾角色的断言最终收紧为匹配具体冲突说明，避免仅因旧字段不存在而虚假验证。
2. `.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_policy.py`：RED 为 **1 collection error**，明确是尚无 `anlan.collaboration` 合同模块，不是外部依赖或环境错误。实现合同/纯策略后，与配置测试一起 **149 passed**。
3. `scripts/dev-postgres.ps1 -Action Start`、`-Action Env` 后运行 `pytest -q tests/test_collaboration_store.py`：RED 为 **12 failed**。资源测试确认 SQL017 不存在；其他测试已通过共享真实 PG fixture 和 `OfflineAnalyzer` 创建原 registry/checkpoint 任务，再因缺少存储模块失败。初步实现后 **12 passed**。
4. 追加尾部空格长度测试：RED 为 **1 failed, 6 passed, 6 deselected**，证明只检查 `btrim` 后长度会允许超过 500 字符的实际存储文本。SQL017 增加原始文本长度约束，重复初始化可补上该约束。开发库中该 RED 探针留下的本批一条测试事件已按其同任务命令中的原 actor 恢复，仅涉及本批 `collab-*` 合成记录；负向 SQL 测试现在使用 `force_rollback=True`，即使检查意外失效也不会提交探针修改。
5. wheel 真实 RED：旧校验脚本报告 `status=failed, resources=17, commands=9`，原因是末尾固定资源数量断言。新增资源校验测试先因缺少 `verify_resources` 失败；提取逐文件校验并移除陈旧总数后通过。
6. 修正后定向验证：schema 负向约束与资源测试 **8 passed, 12 deselected**；首轮六文件回归为 **184 passed**（在追加两项回归前）。下列最终结果覆盖所有最终代码。

最终另建了**全新本地独立测试数据库** `anlan_p12_b1_20261022`，使用项目 PG17（127.0.0.1:55432），没有连接云端。沿用本地私密凭据但未打印 DSN。复现最终测试：

```powershell
scripts/dev-postgres.ps1 -Action Env
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL -replace '/anlan_dev$', '/anlan_p12_b1_20261022'
$env:ANLAN_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_config.py tests/test_collaboration_policy.py tests/test_collaboration_store.py tests/test_conversation_store.py tests/test_service_api.py tests/test_package_layout.py --junitxml=.runtime/p12-b1-evidence/fresh-pg.xml
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
```

最终结果：**186 passed in 28.80s，0 failed / 0 errors / 0 skipped**；Ruff：`All checks passed!`。分项为配置12、策略137、存储13、原会话存储13、原服务API4、包布局7。JUnit 保存在 ignored 的 `.runtime/p12-b1-evidence/fresh-pg.xml`。这不是全仓完整测试套件的结果。

真实 PG 覆盖：四路并发 ensure_draft 幂等、原 registry 整行/owner/thread/initial_state 不变、checkpoint 读取结果不变、指定核查人可见性、同租户未分配/跨租户/legacy 拒绝、重新构造存储及重复初始化后四表行不变、原私有会话不变且安全人员不能读取、正版本/阶段/动作/有界文本约束、跨申请 request_id 冲突、收件去重和跨租户通知 FK。事件/通知/回执由测试直接 SQL 种入，未冒充已实现命令闭环；本批验证的是数据库重连，不是完整应用进程重启。

构建与离源码校验：

```powershell
uv build --wheel --out-dir .runtime/p12-b1-wheel --offline
.venv/Scripts/python.exe scripts/verify_package_layout.py --wheel .runtime/p12-b1-wheel/anlan-0.1.0-py3-none-any.whl --output .runtime/p12-b1-wheel/layout-green.json
```

使用已有缓存离线构建，未增加依赖。结果 `status=completed, resources=17, commands=9`，所有包模块从 wheel 隔离导入，SQL017 确实存在且字节等于源码。wheel SHA256：`aa98dfd1aa1011b50f5e101d7d340f04f8d6eb4e0bd5c422966035612cb0c944`。此处未启动 wheel HTTP 服务，后续 B4 负责完整运行/恢复 Gate。

## 公共合同和函数

`Identity` 未增加角色字段，仍禁止额外输入。`TokenGrant.collaboration_role: Role | None = None` 只由服务端配置提供。同 tenant/user 的多个 token 可以重复同一角色，但 `applicant`/`safety_manager` 以及 `None`/显式角色组合均视为矛盾并拒绝。

```python
ServiceConfig.collaboration_role(identity: Identity) -> Role | None
ServiceConfig.collaboration_reviewers(identity: Identity) -> list[Identity]
```

名单仅包含同租户 `safety_manager`，按 user_id 排序去重，排除本人，不暴露 token。未知身份的角色为 None。

`contracts.py` 导出计划指定的 `Role`、`ApplicationStatus`、`Action`、`ApplicationRecord`。记录字段：task_id、tenant_id、applicant_user_id、reviewer_user_id、status、version、submitted_material_revision、completed_material_revision、created_at、updated_at。记录不可变，拒绝额外字段；版本/材料 revision 严格正整数，draft 无核查人/提交 revision，非 draft 必须有二者，只有 review_completed 有 completed revision 且等于 submitted revision。时间在纯策略构造中可缺省，PG 返回始终有实际时间。

```python
authorize(actor: Identity, role: Role | None,
          application: ApplicationRecord, action: Action) -> None

CollaborationStore(dsn: str)
await store.initialize() -> None
await store.ensure_draft(actor: Identity, role: Role | None,
                         task_id: str) -> ApplicationRecord
await store.get(actor: Identity, role: Role | None,
                task_id: str) -> ApplicationRecord
await store.list(actor: Identity, role: Role | None,
                 limit: int = 100) -> list[ApplicationRecord]
```

`initialize` 需要先有原 registry schema（`initialize_database`），迁移使用事务 advisory lock 73421117。它不会自动扫描或分享旧任务。`ensure_draft` 在事务内检查原 registry 的 tenant/user owner，并用 `ON CONFLICT DO NOTHING` 保留既有协作阶段/版本；不是重置为 draft。所有读取经过纯权限策略。返回 Pydantic 记录，HTTP 层可用 `model_dump(mode="json")` 做受限投影。

`list` 限 1–100 条（缺省100），按 updated_at 降序、task_id 排序，目前无分页 cursor；legacy/未知角色调用 list 抛 AccessDenied，合法角色无匹配资源返回空列表。`get` 资源不存在/无权均 AccessDenied。没有资源权限或角色不允许该动作时 AccessDenied；已有权限但业务阶段错误时 InvalidTransition。

策略：申请人可读取本人申请/事件结果；编辑仅 draft/changes_requested，submit 仅 draft，resubmit 仅 changes_requested。被指定安全人员在首次提交后可读，request_changes/complete_review 仅 under_review。按设计“本人已分配申请”范围，run_event_review/record_event_feedback 在非 draft 阶段允许进入后续命令检查，包含 changes_requested/review_completed；策略允许不等于已实现业务执行或模型调用。安全人员不能编辑/提交材料；申请人不能人工核查或发起事件核查。此策略不授予任何人的私人会话读取权。

## SQL017 表与约束

所有表/索引写入显式 `anlan_v2` schema，迁移版本标记17，不重写原任务或预算行。

| 表 | 字段和关键约束 |
|---|---|
| collaboration_applications | task_id PK/FK→原 anlan_tasks；tenant_id、applicant_user_id、reviewer_user_id、status、version、submitted_material_revision、completed_material_revision、created_at、updated_at；tenant/task UNIQUE；禁止自核查；阶段/空值/完成 revision 一致性；申请人和核查人列表索引 |
| collaboration_commands | tenant_id、actor_user_id、request_id 联合 PK（跨 task 同样冲突）；task_id、action、actor_role、expected_application_version、expected_material_revision、payload、result、created_at、completed_at；tenant/task FK→application；四种命令及其角色配对；result 非空，供一次事务落成功回执，未开放 pending 命令 API；任务索引 |
| collaboration_events | event_id PK，tenant/event UNIQUE；tenant_id、task_id、actor_user_id、actor_role、action、material_revision、application_version、payload、created_at；tenant/task FK；四种命令动作及 run_event_review/record_event_feedback，校验角色配对；任务时间线索引 |
| collaboration_notifications | tenant_id、recipient_user_id、event_id 联合 PK；tenant/event FK→event；ordinal bigint identity UNIQUE、created_at、read_at；按 tenant/recipient/ordinal 收件索引；不存任何私聊副本 |

所有自由文本标识符最大500字符且非空（原始长度和 trim 后长度均约束）；enum 固定集合，版本 >=1，JSON payload/result 必须为 object 且序列化文本 <=32768 UTF-8 字节。收件人是否仍为合法参与者、指定 reviewer 是否来自当前配置、审计 actor 是否为真实当前调用者由后续服务层校验，不能仅依赖 FK。ordinal 可以有间隙，不作为业务成功次数。

## B2 必接的锁与事务边界

1. 本批没有给 store 增加业务命令或新的 task 锁。原 `PostgresRegistry.locked` 的协议是 `pg_try_advisory_lock(hashtextextended(task_id, 0))`，session 级锁；`postgres_service` 的 registry 和 checkpoint saver 共用同一个 autocommit 连接，并用 registry `_serial` 保护连接内执行。
2. B2 的 TaskAccess 必须先以真实 actor/可信 role 校验 tenant、参与关系和动作，再解析明确命名的 storage_scope。owner 只能作为底层定位条件，不能替换真实 actor 授权或记审计。不能借申请人 Identity 替安全人员跑整条服务。
3. 材料写入和 submit/resubmit/complete 必须复用上述同一个 task 锁协议。在持锁连接上读取真正 checkpoint/pending operation，检查材料状态、完整性、revision 和应用 version；不要在独立短连接上检查后释放锁再提交，也不能只锁协作表。
4. 新命令在同一 PostgreSQL 事务内更新 application（行锁/预期版本条件）、追加真实 actor 的 event、对应 recipient 的 notification、最终 command result。所有写均使用同一个事务连接；失败一并回滚。B1 的 `get/ensure_draft` 会自开连接，B2 不应把它们当作持锁事务内的原子读写接口，需要扩展 store 以接收/复用连接。
5. 利用 commands 联合 PK 做最终幂等约束，重放必须比较 task/action、双 expected version 和完整 payload；同 tenant/actor/request_id 跨 task 也不能复用。并发首次写需处理唯一键冲突后读取原回执/比较，不要误回另一个申请结果。
6. 模型调用不纳入这个短 PG 原子事务；材料操作的锁/恢复边界必须完整保留。under_review/review_completed 的冻结检查要覆盖旧 resume/revise/recover、Graph、HTTP 和会话入口，而不仅是新增命令 URL。
7. 通知读取后续还需校验当前配置与申请参与关系；仅有 recipient/event FK 不等于自动授权。四表已经具备收件去重及租户关联边界，但本批没有收件箱/SSE接口。

## 遗留与范围结论

B1 指定工作和六文件回归已完成，可交协调会话独立复核。没有已知 B1 阻塞项。B2 尚需实现共享业务授权、HTTP、原入口冻结、原子命令/幂等回执和通知读取；B3 才接独立会话、确认卡片、事件执行、UI。分页 cursor 如需支持大量申请，应由后续批次明确增加；当前列表有界返回100条。

尚未运行全仓测试、双浏览器、进程重启、完整协作往返、云端部署、真实模型或视频。未修改 P12 总状态/验收勾选，未启动 B2。
