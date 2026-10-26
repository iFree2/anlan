# P13 B1 交接：可信目录、绑定合同与持久化

日期：2026-10-26。起点 `6acdf09`，同检出串行实施。本文件随 B1 实现提交；实际提交号以本批 `git log` / 会话交付为准。B1 实现及本地验证完成，待协调独立审查；不代表整个 P13 已完成或已上线。未修改总验收清单、阶段 README 或 coordinator-check。

## 已交付文件与接口

- `src/anlan/preflight/{__init__,contracts,catalog,bindings}.py`
- `src/anlan/infrastructure/preflight.py`
- `src/anlan/sql/019_preflight_bindings.sql`
- `src/anlan/interfaces/service_config.py` 仅增加目录配置及租户去重校验。
- `tests/test_preflight_{contracts,catalog,bindings,store}.py`
- 本交接及 `evidence/b1/` 下无凭据证据。

`TokenGrant`、`Identity`、audit_only 政策与旧迁移均未修改。不接 HTTP、UI、自动事实/知识查询、提交或完成门控，不改变当前线上行为。没有相邻配置/资源断言调整。

公共合同均继承 StrictModel，拒绝额外字段：

- `BindingCommand(request_id, expected_material_revision>=1, expected_binding_revision>=0, worker_id, qualification_type, area_id)`；版本严格 int，拒绝 bool/字符串；请求号保留原文用于完整载荷比较。
- `BindingRecord(task_id, binding_revision>=1, material_revision_at_confirmation>=1, references: FactReferences, confirmed_by: Identity, confirmed_at: AwareDatetime)`。确认时间来自真实 PG 时钟，独立于后续证据的业务回放时钟。
- `PrecheckPolicy(task_id, required: strict bool, legacy_completed: strict bool)`；二者恰有一个为真。
- `EvidenceKey(task_id, material_revision, binding_revision, application_version)`，各版本严格正整数。
- 目录类型：`CatalogQualification(qualification_type,label)`、`CatalogWorker(worker_id,label,qualification_types)`、`CatalogArea(area_id,label)`、`ObjectCatalog(workers,areas)`、`PrecheckCatalog(tenant_id,workers,areas)`。

`BindingService(dsn, config, service_context_factory)` 异步入口：

- `catalog(actor, task_id) -> ObjectCatalog`：任务参与者鉴权后，返回服务器过滤过的目录。
- `get(actor, task_id) -> BindingRecord | None`：读取当前 head；返回已绑定对象前重新验证调用者的目录/事实 ACL。
- `confirm(actor, task_id, payload) -> BindingRecord`：仅实际 storage owner 且当前可信角色为 applicant、申请处于 draft/changes_requested 时允许。

## 目录配置与授权

`ServiceConfig.precheck_catalogs` 默认为空列表，兼容旧配置。示例结构如下；示例仅说明合同，未写入演示/线上配置：

```json
{
  "precheck_catalogs": [{
    "tenant_id": "synthetic-tenant",
    "workers": [{
      "worker_id": "worker-a", "label": "合成人员甲",
      "qualification_types": [{"qualification_type": "welding", "label": "合成焊接资质"}]
    }],
    "areas": [{"area_id": "area-a", "label": "合成区域甲"}]
  }]
}
```

可信 ID 复用 ObjectId，普通姓名/中文地点不能充当 ID。标签非空且有长度上限；重复租户/人员/区域/人员资质类型、同类型冲突标签均拒绝。没有默认勾选字段或 console profile 回退。

`CatalogService(config).visible(actor)` 每次有界读取 facts_dir 的 `access.json`，复用 AccessData：只取相同 tenant+真实 user 的 grants，与可信目录交集后返回；不向调用方返回全租户元数据。授权源缺失、错误、超限或超时抛 AccessDenied。目录不读取 qualifications/areas 事实记录，因此获授权但事实缺失的对象仍可列选，未编造资质/区域状态。

`validate(actor,references)` 同时核对人员、该人员允许的资质类型和区域。confirm、get 回执及读取不借用 owner/管理员/安全人员的工具权限。安全人员只有被分配且非 draft 才能读对应申请，还必须拥有自己的 facts ACL；不能代改绑定。第三者、跨租户、角色移除、对象 ACL 撤销均受控拒绝。

## 锁、版本和事务

confirm 先通过真实 `PostgresRegistry.locked(actor,task_id,action='read')`，随后核对申请人权限/阶段、storage owner、contract/mode、真实 checkpoint 材料版本、awaiting_review 状态、next/interrupts 和 pending 操作。waiting_input、checkpoint 缺失及待恢复材料操作不能确认。目录 ACL 有界 I/O 在写事务之前执行，期间仍持有真实 task 锁。

写事务顺序与 P12 一致：task 会话 advisory lock → actor/request 事务 advisory lock → application FOR UPDATE → 版本/head/回执写入。新增命名空间为 JSON 数组 `['precheck-binding-command-v1', tenant, actor, request_id]`，`hashtextextended(...,19)`；不占用 P12 的 request/通知命名空间，不颠倒其锁顺序。

新请求比较真实材料版本与当前 binding head（无绑定时 revision=0）；变更对象产生下一版，不修改原四项材料、不递增材料版本。同对象、正确双版本的新确认只增加回执，不虚增绑定版本或重写首次确认信息。

同 actor/request、相同 task 与完整载荷返回原确认记录；变载荷或跨 task 冲突。重放之前仍核对当前权限、可编辑阶段、材料 checkpoint/版本和 ACL。回执表达原确认，不保证仍是最新 head；后续调用方需要通过 get/同锁下的 get_binding 取得当前绑定。版本、head、回执位于同一 PG 事务，写回执前失败全部回滚。registry 锁竞争沿用 TaskBusy。

## SQL019 与内部存储入口

四张新表均位于 `anlan_v2`：

| 表 | 主要合同 |
|---|---|
| `precheck_policies` | task 主键、tenant、required、legacy_completed、created_at；required 与 legacy 互斥 |
| `precheck_binding_versions` | PK(tenant,task,binding_revision)；确认时材料版本、三对象 ID、确认人、PG 时间 |
| `precheck_binding_heads` | task 主键；tenant+task+binding_revision 外键指向真实版本 |
| `precheck_binding_commands` | PK(tenant,actor,request_id)；task、预期双版本、结果 binding_revision、完整 payload/result、时间 |

task 外键指向 registry，tenant+task 外键经 collaboration_applications 约束租户；head/command 有复合版本外键。对象格式、正版本、文本/JSON 大小均有限制。versions/commands 的 BEFORE UPDATE OR DELETE 触发器禁止重写历史。

`PrecheckStore.initialize()` 仅创建表/触发器/索引及 migration=19；不批量激活旧申请策略。独立初始化 advisory 事务锁 `73421119` 下，整份 SQL 在同一 PG 事务执行。触发器用 `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER`，而非 PG14 新增的 OR REPLACE 形式；依据 [PG13 CREATE TRIGGER](https://www.postgresql.org/docs/13/sql-createtrigger.html)、[PG13 DROP TRIGGER](https://www.postgresql.org/docs/13/sql-droptrigger.html) 与 [PG14 语法](https://www.postgresql.org/docs/14/sql-createtrigger.html)核对。**这是 PG13 语法兼容审查；本批实际运行环境仅 PG17，未声称实跑 PG13。**

内部入口（调用方须先完成任务授权；写入须复用 task 锁和事务连接）：

- `ensure_policy(tenant_id,task_id,*,conn=None)` 从真实协作申请 stage 派生初始策略；旧已完成记 legacy，旧未完成 required，ON CONFLICT 保留后续策略。private legacy 无协作行则拒绝。
- `get_binding(tenant_id,task_id,*,conn=None)` 读取当前 head。
- `write_binding(conn,actor,task_id,command,current)`、`receipt(conn,actor,request_id)`、`save_receipt(conn,actor,task_id,command,result)` 供已授权事务使用，不是 HTTP 授权入口。

## 实际验证与证据

真实本地 PostgreSQL **17.11 / server_version 170011**，`127.0.0.1:55432` 独立库 **anlan_p13_b1_20261026**。通过项目 `dev-postgres.ps1 Start/Env` 取得本地环境，仅替换库名，并经 psycopg 对同一 loopback 实例显式创建该库；未读取云端凭据、未改系统 PG10、未 SSH。DSN/密码不打印、不入库外证据。

| 步骤 | 实际结果 | 证据 |
|---|---|---|
| 合同/目录 RED | 21 failed、6 passed；失败为新模块缺失，6 项旧配置拒绝用例原已通过 | `contracts-catalog-red.xml` |
| 合同/目录 GREEN | 27 passed | `contracts-catalog-green.xml` |
| 真实任务/PG RED | 27 failed；先创建实际 OfflineAnalyzer 材料任务/checkpoint，再因新 store 缺失失败，另含 SQL 资源缺失 | `bindings-store-red.xml` |
| 首轮 PG GREEN | 27 passed | `bindings-store-green.xml` |
| PG13 DDL 针对性 RED | 1 failed、10 deselected，准确发现 OR REPLACE TRIGGER | `pg13-ddl-red.xml` |
| PG17 重复初始化与历史保护 GREEN | 13 passed，含双方表 UPDATE/DELETE 拒绝 | `pg13-ddl-pg17-green.xml` |
| 最终指定回归组合 | **105 passed，0 failed/error/skip**；新增四文件 57 项，其他指定文件 48 项 | `regression-green.xml` |
| Ruff | 全目录 0 finding | `ruff.json`（空数组） |
| wheel 离源码 | 103 modules、19 resources、9 CLI 入口通过；SQL019/旧迁移均按源码逐字节校验 | `wheel-layout.json` |

初始测试构造曾因超长参数名触发 Windows 临时目录错误；加入短参数 IDs 后才保存合同/目录 RED。首轮 PG 实现后两项测试修正为：在可编辑阶段测试撤权、直接观察 pg_locks 而非固定的 pg_stat_activity 事务快照；没有放宽旧权限/阶段规则。

最终回归准确命令：

```powershell
. ./scripts/dev-postgres.ps1 -Action Env | Out-Null
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_DATABASE_URL -replace '/anlan_dev$', '/anlan_p13_b1_20261026'
.venv/Scripts/python.exe -m pytest -q tests/test_preflight_contracts.py tests/test_preflight_catalog.py tests/test_preflight_bindings.py tests/test_preflight_store.py tests/test_collaboration_config.py tests/test_collaboration_store.py tests/test_service_api.py tests/test_package_layout.py tests/test_demo_short_tokens.py -m 'not live_model' --junitxml=docs/phases/phase-13-preflight/evidence/b1/regression-green.xml
.venv/Scripts/ruff.exe check src tests evals scripts deploy --output-format json --output-file docs/phases/phase-13-preflight/evidence/b1/ruff.json
uv build --wheel --out-dir .runtime/p13-b1-dist
.venv/Scripts/python.exe scripts/verify_package_layout.py --wheel .runtime/p13-b1-dist/anlan-0.1.0-py3-none-any.whl --output docs/phases/phase-13-preflight/evidence/b1/wheel-layout.json
```

wheel verifier 使用排他创建输出；复验时指定新输出路径。制品位于本地忽略目录 `.runtime/p13-b1-dist/anlan-0.1.0-py3-none-any.whl`，SHA256 `3cce263e2d075e7f91f849ae11e6472b7537ae78dcd45863ae9c1523a9bd06bb`。Junit 精确耗时见 XML，最终 pytest 终端为 105 passed in 52.99s。该组合无 live 项被收集/选择；用户未提交的 `test_tool_loop_live.py` 未执行，不以本结果冒充全测试目录 Gate。

覆盖两组不同授权对象（即使事实文件不存在仍能列选）、目录 ACL/读取失败、请求注入、双版本/重连/并发、阶段冻结、完整幂等载荷/跨任务命名空间、回执前崩溃回滚、SQL 外键/唯一性/不可变历史。旧记录检查保留真实 completed 历史、材料任务/checkpoint、协作行、私聊及独立合成 audit_only 账本；账本测试仅创建隔离审计哨兵，不发模型请求、不重置历史。

## 后续接入点与限制

B2 需明确初始化/升级策略并在新任务注册、提交、结果写入和完成路径复用上述合同与 task 锁；持久化 job/attempt/result、来源当前性、人工引用确认和完成门控均未实现。B3 才接对象目录/绑定 HTTP、双角色 UI/对话和事件绑定复用；不能把本批目录测试当成三项查询或浏览器闭环验收。没有改动既有“重提需新材料版本”规则，后批仍须扩展为绑定/来源变化的合法路径。

未做 PG13 实跑、云端发布、真实模型调用、双浏览器、自动预核查或整体 P13 Gate。保留用户 dirty 的 roadmap、status P10 段落、phase-10 目录、test_tool_loop_live.py 和 .superpowers/；未创建 worktree、其他会话或子代理。
