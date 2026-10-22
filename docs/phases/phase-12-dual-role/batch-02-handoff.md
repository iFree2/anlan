# P12 B2 交接：共享授权与可恢复协作命令

日期：2026-10-22（Asia/Shanghai）。实施基线为当前 local 检出 `528de21`，前置 B1 实现 `6854844`、交接 `2f18764`、协调验收 `07d6800`。本批代码提交为 **`201b83adafb2044eea1dd6ef9a214b8a29ff7c36`**（`feat: add atomic dual-role material collaboration commands`），本交接另行提交，可用 `git log -1 -- docs/phases/phase-12-dual-role/batch-02-handoff.md` 查询。本批只执行已批准计划的 B2；没有创建 worktree、其他会话或子代理，没有 SSH、部署或真实模型调用。

## 文件范围

- 新增 `src/anlan/collaboration/access.py`、`service.py`、`src/anlan/interfaces/collaboration_routes.py`。
- 扩展 `src/anlan/infrastructure/collaboration.py`、`postgres.py`、`src/anlan/workflows/registry.py`、`service.py`，以及 `src/anlan/interfaces/runtime.py`、`service_models.py`、`api.py`。
- 最小相邻修改 `src/anlan/interfaces/console/routes.py`、`service.py`：可信角色/能力信息，以及新角色尚未接通的事件能力拒绝。
- 新增 `tests/test_collaboration_service.py`、`test_collaboration_api.py` 和本交接。

沿用 SQL017 的现有四表，**未修改任何迁移，也不需要 SQL018**。SQL012、预算合同和账本没有改变。没有修改 P12 总批次状态或验收勾选。未暂存用户原有的 `docs/roadmap.md`、`docs/status.md`、`.superpowers/`、`docs/phases/phase-10-dynamic-mcp/`、`tests/test_tool_loop_live.py`；没有使用 `git add -A`。协调对 P12 README 的更新属于协调自己的提交。

## RED → GREEN 与真实 PG

使用本地 PostgreSQL17，`127.0.0.1:55432`，新建独立库 `anlan_p12_b2_20261022`，未访问云端。测试用原工作流创建真实 registry/checkpoint，不使用内存替身代替 PG。分析器为 `OfflineAnalyzer`，不声称真实模型质量验证。

1. 首次运行两个新增测试文件：**11 failed**。已有 PG 初始化和任务创建成功；失败分别为协作路由不存在、可信能力信息缺失、安全人员仍可创建任务、原子回执边界及 `access_config` 注入缺失。证据 `.runtime/p12-b2-evidence/red.xml`。实现后同两文件 **11 passed in 24.20s**。
2. 扩展完整载荷、实际 checkpoint、材料新版本、注册崩溃窗口、跨任务并发幂等检查：**1 failed, 7 passed**。失败明确复现文本去空格后，变载荷被当成原命令重放。改为非空但保留原始文本的严格命令字段，再比较完整 payload。
3. 锁中权限探针：**1 failed**，同租户未参与者在任务忙时收到409，能区分资源状态。增加锁前授权预检，锁内仍重新执行权威授权；未参与者统一404。
4. checkpoint错误残留/核查人标识探针：**2 failed**。一项复现 `semantic_status=checked` 但仍含分析错误时可提交；另一项复现核查人标识带尾部空格被 Identity 正规化后通过名单校验，却向存储写入原字符串。现拒绝分析错误，并要求核查人标识与可信配置精确一致。
5. 修正前一轮计划九文件回归为 **198 passed in 99.03s**，仅作为中间证据；下面最终结果覆盖后续两个新增探针和修正。

最终复现命令：

```powershell
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL -replace '/anlan_dev$', '/anlan_p12_b2_20261022'
$env:ANLAN_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_policy.py tests/test_collaboration_store.py tests/test_collaboration_service.py tests/test_collaboration_api.py tests/test_postgres.py tests/test_material_revisions.py tests/test_service_api.py tests/test_service_reliability.py tests/test_conversation_api.py --junitxml=.runtime/p12-b2-evidence/final-regression.xml
.venv/Scripts/python.exe -m pytest -q tests/test_console.py tests/test_conversation_runtime.py tests/test_conversation_service.py tests/test_conversation_recovery.py tests/test_workflow.py tests/test_recovery.py tests/test_package_layout.py --junitxml=.runtime/p12-b2-evidence/adjacent.xml
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
git diff --check
```

最终计划九文件：**200 passed in 138.06s，0 failed / 0 errors / 0 skipped**。相邻七文件：**68 passed in 136.66s，0 failed / 0 errors / 0 skipped**。两个JUnit的tests/failures/errors/skipped字段已再次读取核对。最终 Ruff：`All checks passed!`；`git diff --check` 与本批文件暂存后的 `git diff --cached --check` 均无错误。所有 JUnit 放在 ignored 的 `.runtime/p12-b2-evidence/`，不含 DSN 或 token。没有把本批结果称为全仓测试通过。

## 服务与 HTTP 合同

`CollaborationService(dsn, config, service_context_factory)` 使用服务端的 `ServiceConfig` 和 `models.material_service`。公共方法：`list(actor)`、`get(actor, task_id)`、`execute(actor, task_id, action, payload)`、`notifications(actor, after=0, limit=100)`。不接受客户端角色、owner 或 storage_scope。B3 确认冻结载荷后应调用 `execute`，而非直接操作协作表。

| HTTP | 返回/载荷 |
|---|---|
| GET `/collaboration/applications` | `{items: ApplicationRecord[], limit: 100}`，申请人本人申请/安全人员被指定的非draft申请 |
| GET `/collaboration/applications/{task_id}` | `{application, materials, events, notice}`；材料白名单只有task_id/fields/revision/status/analysis_mode |
| POST `.../commands/submit` | 公共字段 + `reviewer_user_id`，只接受当前同租户可信名单中的另一人 |
| POST `.../commands/request_changes` | 公共字段 + `questions: list[str]`，1–20条，各条非空且至多500字符 |
| POST `.../commands/resubmit` | 公共字段 + 非空 `reply`，必须有新材料revision，维持原核查人 |
| POST `.../commands/complete_review` | 公共字段 + 非空人工 `conclusion`；完成绑定已提交且仍为最新的材料revision |
| GET `/collaboration/notifications?after=0&limit=100` | `{items: [{ordinal,event}], next_cursor, limit}`，稳定event_id；limit为1–100，after为非负整数 |

所有 POST 公共字段为 `request_id`、`expected_application_version`、`expected_material_revision`。请求严格禁止额外身份/角色字段；版本为严格正整数。字符串保留精确内容做重放比较，纯空白拒绝。成功命令返回 `{application, event_id, notice}`，同载荷重放逐字段返回最初已提交结果，即使申请后来已前进。改动作、双版本、任何payload内容或跨task复用同tenant/actor/request_id返回409；撤权后不能借原回执读资源。

匿名401，无资源权限/角色不允许动作404，阶段/材料/版本/任务忙/待恢复409，非法字段422；沿用安全错误响应，不暴露异常详情。`GET /tasks/{task}` 对被指定安全人员返回同样的材料白名单；原owner可读取自己的完整任务。原 `/history` 仍为owner私有，不向安全人员公开执行request_id/run_id。

`GET /console/api/info` 增加 `collaboration_role`、`capabilities` 与申请人的 `collaboration_reviewers`（只含user_id，不含token）。新角色 `run_event_review`/`record_event_feedback` 为false，simulation_enabled为false。新角色对旧通用事件/核查/反馈/恢复/SSE和控制台模拟/事件路径均拒绝；不能把B1纯策略的未来允许项当作事件执行已接通。

## 授权、锁顺序与事务

`TaskAccess` 在原registry行中解析明确的 `storage_scope`，但角色判断和协作审计使用传入的真实actor。安全人员从未作为申请人Identity调用整条业务服务。`TaskRecord.identity` 保持原任务owner，限于原线程/checkpoint定位；安全人员命令事件写其自己的 user_id/role。

锁顺序：单连接 `_serial` → 权限预检 → 原 `pg_try_advisory_lock(hashtextextended(task_id,0))` session锁 → 再次授权 → 短事务 → tenant/actor/request_id 的事务advisory锁（seed=1）→ 协作行FOR UPDATE → 幂等比较 → 当前材料checkpoint/pending/双版本校验 → 状态、事件、通知、最终回执 → 提交 → 释放任务锁。跨task相同请求被请求级锁串行化，联合主键仍为最终数据库约束。

所有命令读写共用registry/checkpointer的同一连接。`CollaborationStore.get(..., conn=..., for_update=True)`、`ensure_draft(..., conn=...)` 可复用调用者连接；transition、append_event、save_receipt只能在调用方事务中执行。状态变化、真实actor事件、对应收件人通知和最终回执在一个事务里，回执前故障全部回滚。命令执行只读材料checkpoint，不调用模型。

材料执行仍沿原任务锁和checkpoint恢复协议运行；**没有把长模型调用包进协作短事务**。`resume/revise/recover/start重放` 在进入执行或返回缓存结果前检查编辑阶段。`under_review/review_completed` 冻结写入；没有role resolver的旧PG组合也检查持久化冻结。服务内部Graph写入口要求当前async任务持有该task的授权编辑锁，并再次检查冻结；裸ainvoke/aupdate_state和其他执行入口拒绝。

新申请人的registry创建与draft注册处于同一短事务，随后才reserve/执行Graph；创建后、reserve前崩溃可按同task恢复。`ensure_draft` 可重入且不重置已有阶段。legacy任务不自动登记或共享，原owner私有访问保持；安全人员不能创建或编辑材料。会话适配器复用带可信配置的 `models.material_service`，因此同样受冻结和角色约束。

## 覆盖与 B3 接入边界

本批两个真实Identity、两独立HTTP clients完成：申请→submit→安全人员request_changes→申请人revise至revision2→resubmit→安全人员complete_review；task_id不变，应用版本1→5，人工核查绑定revision2，不写approved/许可或开工指令。时间线保留四个动作与真实actor。也覆盖同租户未分配/其他申请人、跨租户、legacy、匿名、私密执行字段投影、旧HTTP/服务/Graph/会话适配器冻结、双完成并发、跨task并发请求ID、回执前回滚、pending材料恢复、实际checkpoint未就绪和无新revision重提。

通知每次读取重新从当前可信配置取得role，并对每条event的当前申请参与关系执行authorize；猜测他人ordinal不会读取其收件箱。撤权或不再是指定核查人时不能读原通知。通知只引用业务event，不复制任何私人聊天或conversation_id。分页可能返回空页但next_cursor仍前进（过滤掉已失去访问权的事件）；调用方应保存next_cursor。申请列表/时间线目前有界100条，没有时间线翻页接口。

B3 必须接入：

1. 四种会话候选与持久化确认卡片。冻结完整action/task/双版本/核查人或问题/说明，确认后原样调用 `CollaborationService.execute`；候选阶段不能提前调用。候选 `submit_application/request_changes/resubmit_application/complete_material_review` 分别映射服务动作 `submit/request_changes/resubmit/complete_review`。B2的确定性HTTP接口不等同对话确认已实现。
2. 安全人员本人会话绑定共享task，独立private conversation保持原权限。使用共享投影，不能把原owner完整checkpoint、私聊、私密异常或对方conversation_id送入模型。旧 `WorkflowAdapter.TaskProjection` 面向申请人材料引导，不能直接作为管理人员的完整业务投影；B3应组合collaboration投影/能力。
3. 本人待办、通知轮询/认证快照流及event_id去重。重连从本人保存的next_cursor补读，不通过读取对方会话取得进展。
4. 事件模拟/核查/反馈的真实actor和显式storage_scope适配。当前新角色入口故意关闭；需完成参与关系、来源、receipt/review、材料revision和audit边界及测试后才能开放，不能直接删除LegacyActor/require_legacy_events检查或冒用申请人Identity。
5. 双角色UI、浏览器与进程重启验收，以及后续发布/视频均未开展。本批没有进行独立审查者复核；遵守本批禁止派发子代理/发送其他会话消息的要求，由协调另行验收。

没有已知 B2 阻塞项，待协调独立验收后进入B3。本批保留当前分支和local检出，未合并或推送远端。终点仍是**材料核查完成**，不代表正式批准或开工授权。
