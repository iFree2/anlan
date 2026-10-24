# P12 B3 交接：双角色对话、通知与事件核查

日期：2026-10-24（Asia/Shanghai）。实施起点为 B2 协调验收 `24c38b8`；恢复本会话时 HEAD 为协调文档提交 `a12151f`。本批实现提交：`4726f27eda00d4236fc14ab42228c50655e20751`。本文以独立文档提交交付，可用 `git log -1 -- docs/phases/phase-12-dual-role/batch-03-handoff.md` 查询文档提交。

只实施已批准的 B3，沿用当前 local 检出和分支，未创建 worktree、其他会话或子代理，未向其他会话发消息。未 SSH、部署、调用真实模型或录云端视频，未开始 B4 全仓/发布 Gate。终点为材料核查完成，不是正式审批或开工授权；未增加申请阶段证据预核查主流程、真实设备、P9/P10 或预算。

## 文件与迁移

- 扩展 `conversation/contracts.py`、`policy.py`、`service.py`、`llm/conversation.py`，以及 `interfaces/conversation_runtime.py`、`conversation_routes.py`、`api.py`。
- 新增专用 `interfaces/collaboration_conversation.py`、`collaboration/event_access.py`，分开角色投影/确认执行与事件资源授权，未把全部协作放进旧会话类。
- 扩展 `infrastructure/conversations.py`、`events.py`、`perception.py`、`interfaces/event_runtime.py`、`perception_runtime.py` 和 console routes/service/assets。
- `infrastructure/collaboration.py` 仅调整同申请版本内事件的时间线顺序为 `application_version,created_at,event_id`；保留 B2 的 tenant/recipient seed=2 事务锁、通知 ordinal 分配和提交顺序。
- 新增 `tests/test_collaboration_conversation.py`、`test_collaboration_events.py`、`test_collaboration_console.py`、`scripts/prepare_collaboration_demo.py`。必要相邻测试修改 `tests/test_conversation_model.py`：业务字段 `reviewer_user_id` 可以出现在 schema，但真实认证 identity/tenant 的哨兵仍不能进入供应商请求；现解析模型上下文后检查，未弱化为忽略身份。

**没有修改 SQL012/013/017，也不需要 SQL018。** 既有 `pending_intents.candidate` 和 `conversation_routes.decision` 的 JSON 已可保存完整确认合同；结构化请求的完整载荷另保存在既有消息 `request_payload.structured_candidate` 中用于幂等比较。没有新包或账本重置。

保留原有 dirty 路径 `docs/roadmap.md`、`docs/status.md`、`.superpowers/`、`docs/phases/phase-10-dynamic-mcp/`、`tests/test_tool_loop_live.py`，没有 reset/checkout 恢复或 `git add -A`。没有修改 P12 README 或验收勾选。

## 确认、本人会话与模型边界

四类意图 `submit_application/request_changes/resubmit_application/complete_material_review` 分别映射 B2 的 `submit/request_changes/resubmit/complete_review`。候选阶段只写本人会话，不写协作状态、不提前通知。

`FrozenCollaborationCommand` 保存 action、task_id 和完整 B2 payload：原 request_id、expected_application_version、expected_material_revision，以及 reviewer_user_id/questions/reply/conclusion。确认路由也保存这一冻结对象，之后原样调用 `CollaborationService.execute(real_actor, task_id, action, payload)`。不在确认时补取新版本或重解释说明。拒绝、引用“确认”、闲聊、旧版本和旧会话卡片均不能推进业务；B2 成功命令重放仍返回原回执且不重复事件/通知。

结构化候选的幂等比较包含完整输入，不能用同一 request_id 更换核查人或说明而拿回旧候选。卡片被替换时会话 revision 前进，旧卡片提交的 expected_revision 被拒绝。暂停/恢复新角色引导只改变本人会话绑定状态，不借材料 recover 写入冻结申请。

新增接口（actor/role 均从认证配置取得，载荷禁止注入）：

| 接口 | 载荷 / 语义 |
|---|---|
| POST `/conversations/{id}/task` | `task_id, expected_revision`；先验证本人会话与任务参与权，再绑定；外部绑定使会话 revision 前进，旧候选被 supersede |
| POST `/conversations/{id}/collaboration-candidates` | `request_id, expected_revision, intent, collaboration`；collaboration 只允许核查人/问题/说明；不调用分类模型，仍持久化候选并要求确认 |
| 原 `/conversations/{id}/messages` | 自然语言分类也支持四类协作候选；确认沿原明确整句肯定门控 |
| 原 `/collaboration/applications`、`/{task}`、`/notifications` | 本人申请/分配待办、受限时间线与收件箱；读取不调用模型 |

两人是不同可信 Identity、不同 conversation_id、同一 task_id。会话列表和私聊继续按 tenant/user 私有；共享业务消息来自业务事件，不复制对方私人消息或 conversation_id。

申请人从**同一次授权任务锁及 checkpoint 读取**取得本人原 `WorkflowAdapter._project` 安全投影，再合并协作元数据，保留具体 issue_questions 和 checked/offline_not_checked/failed；补充后出现的新问题同时进入侧栏、后续模型上下文和助手追问。没有额外材料模型调用。安全人员始终构造共享白名单投影，使用明确的 `shared_materials` 标识，不把缺少 analysis 误判成 failed，也不返回申请人的分析错误、checkpoint、执行 ID 或痕迹。

提示词、供应商严格 DTO、确定性策略、scripted 替身和公开快照均已适配。供应商上下文继续最多 12 条本人可见消息、16 KiB；共享嵌套 application/event/payload 也有白名单。过大的上下文可省略模型侧卡片摘要，持久化的完整执行载荷从不裁剪。

消息回执重放前会重新授权所有已知资源引用：active_task_id、task_projection（含协作 application）、pending collaboration 和 business_messages。即使角色降为 legacy(None)，或 active_task_id 已空，也不能绕过旧共享内容的授权；正常 legacy 本人私有任务回放保持兼容。

## 通知、轮询与换号

共享角色 UI 使用 **3 秒认证有界轮询**读取本人申请、收件箱和当前会话快照，不同时叠加快速 SSE 读同一个 task 锁。原认证 SSE 接口仍保留，legacy UI 沿用 SSE。只读材料投影和事件列表遇到短暂 TaskBusy 时最多等待 2 秒；只重读，不重发命令、工具或模型。

通知以 event_id 去重，保存服务端 next_cursor，包含过滤撤权消息后 items 为空但 cursor 前进的页。每页最多100条，UI 收件缓存最多200条；重载/重连从0补读持久化收件箱，不把通知插入对方私聊。协作申请/共享时间线仍沿 B2 的100条边界，未新增分页 API。

快照相同不重建确认卡片或业务表单；本人未提交草稿按 task/action 保存在当前页面内存，快照变化后可以保留。更换连接配置或断开时，清空草稿、notifications、cursor、snapshot、会话/事件/核查缓存和 streamId，取消轮询并中止请求/SSE。API 的 connectionEpoch 还会丢弃已换号后才到达的旧响应/回调。凭据只存当前模块内存，不写浏览器持久存储。

同一身份切换本人会话/申请后，迟到的旧快照和旧事件列表也会丢弃，不会把新选择切回旧会话。已选事件的 review 列表、currentness 和反馈随轮询重新读取，材料更新后不会继续显示旧的 current 标签；读取不调用模型。

## 事件真实 actor、storage_scope 与事务

新角色通用原始 `/sources/{source}/events` 接入仍关闭；模拟通过本人分配申请的控制台入口。服务端从已授权 task registry 解析明确的 storage_scope，再用服务端 ConsoleProfile 取得可信 area/worker/qualification 引用和合成来源，不接受 HTTP 的 owner/scope/source/area 参数，也不让模型猜 ID。

授权、固定事实查询、知识检索、模型综合和审计始终使用真实安全人员 actor。原 owner 只定位事件/review 表和材料 checkpoint；没有用申请人 Identity 跑整条核查链。`SharedCollectionReader` 只给采集器白名单材料和公开的 task/revision 标识，记忆读取仍是安全人员本人。

仅被指定安全人员可模拟、发起核查、控制核查和保存反馈；两参与者只读允许共享的事件/核查结果。第三者、未分配和跨租户的 receipt/review/列表/SSE 都拒绝。公开事件/核查投影排除原 checkpoint run ID、模型 context、私密错误和诊断；原始 alarm_state 保留 active。

事件模拟复用原任务锁、事件流锁和幂等边界；review 预留、真实 actor 的 `run_event_review` 业务事件及通知在同一短事务中写入。固定事实查询＋知识检索＋模型综合、来源/时间/材料版本/currentness 校验、取消/恢复和预算网关均保留。反馈复用任务锁、review 行锁和原请求幂等，在同一事务保存 feedback、真实 actor 的 `record_event_feedback` 事件及通知。沿用 B2 收件人事务锁，不重置预算。

新材料 revision 会使旧核查 currentness=stale_material；过期事件和被新事件替代分别保留 expired_event/superseded_event。材料核查完成不关闭报警，也不产生 approved/permit_issued。

legacy 私有回执保持原语义：收件人仍可读取其目标任务缺失/错误绑定的回执，关联阶段记录 task_unavailable，不能写入目标任务。已登记协作申请则必须有可信角色，角色撤销不会变成 legacy 事件授权。

## RED → GREEN 与 PostgreSQL

全程使用本地 PG17 `127.0.0.1:55432` 的独立数据库 `anlan_p12_b3_20261023`，实际创建原 registry/checkpoint，不以 skip 或内存替身代替 PG。分析器/分类器/事件模型为离线或 scripted/协议替身，无真实供应商调用。JUnit 均在 ignored 的 `.runtime/p12-b3-evidence/`，未打印 DSN 或令牌。

- 首轮 conversation RED：6 failed，缺少本人会话绑定接口；实现后6 passed。事件 RED：2 failed，角色事件护栏尚未接通；实现后2 passed。控制台页面 RED 缺少待办/收件箱，演示脚本独立 RED 缺文件；实现后 console 两项通过。
- 模型上下文补强：先复现未绑定安全人员上下文 role=None，以及嵌套共享投影哨兵泄漏；修复可信 role 注入及嵌套白名单。中间一轮测试夹具误用 async with patch 的 TypeError 已修正，角色问题另外独立跑出真实 RED，不作为功能失败冒充证据。
- `-k 'complete_payload or pause_resume'`：RED 3 failed；修复结构化载荷幂等及只恢复本人引导后 GREEN 3 passed。
- Node 轮询 RED 1 failed：相同快照重建卡片；修复后与换号迟到响应/流测试一起2 passed。补充共享 UI 不叠加快速 SSE 的 RED/GREEN，仍为2项 Node 验证。断开清草稿/游标/快照亦在该测试中执行。
- 两项 UI 追加探针分别真实 RED：迟到轮询把新选择改回旧会话；已选 review 在材料变化后仍显示旧 current。各自最小修复后，Node 两项测试分别 GREEN，未借此增加模型或业务写重试。
- `-k transient_task`：RED 1 failed（短暂读锁使投影 unavailable）；有界只读等待后1 passed。
- 草稿文案 RED 1 failed：未提交却声称进入人工复核；修复后1 passed，离线/失败文案又由后续状态测试收紧。
- 协调两项审查：`-k 'revoked_shared or legacy_owner_private or semantic_followups or analysis_status_is_preserved'` → **11 failed, 2 passed**。撤权重放独立 GREEN 为 **9 passed**；申请人语义投影、后续追问与双方隔离 GREEN 为 **6 passed**。前者覆盖 role=None/失去参与关系 × active/projection/pending/business 四种缓存引用，并保留 legacy owner 重放；后者使用真实 PG 和受控语义替身，未调用真实模型。
- 相邻旧事件关联 RED：`pytest -q tests/test_events_postgres.py -k task_association_requires` → **3 failed,1 passed**；legacy 回执与目标任务授权分开后 **4 passed**。同条 GREEN 命令中的 `-k` 会过滤新增事件文件，未把被 deselect 的三项误算通过。
- 中间十文件结果112 passed、追加读竞争探针后113 passed，均0 skipped；这些发生在协调最终修复前，不能代替下面最终结果。
- 首轮十七文件（协调修复后、legacy 兼容修复前）为199 passed、3 failed，0 skipped，JUnit `final-regression.xml`；三项均为上述旧回执关联问题，保留失败证据，不改写成通过。

最终复现命令：

```powershell
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL -replace '/anlan_dev$', '/anlan_p12_b3_20261023'
$env:ANLAN_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_conversation.py tests/test_collaboration_events.py tests/test_collaboration_console.py tests/test_conversation_policy.py tests/test_conversation_model.py tests/test_conversation_service.py tests/test_conversation_api.py tests/test_console.py tests/test_perception_postgres.py tests/test_service_http.py tests/test_conversation_store.py tests/test_conversation_recovery.py tests/test_conversation_runtime.py tests/test_collaboration_service.py tests/test_collaboration_api.py tests/test_events_postgres.py tests/test_package_layout.py --junitxml=.runtime/p12-b3-evidence/final-verified.xml
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
git diff --check
```

**最终结果：17文件定向回归202 passed in 407.65s，0 failed / 0 errors / 0 skipped。** JUnit 的 tests/failures/errors/skipped 已另行读取核对。 最后的选中核查详情刷新仅修改 UI 后，另行运行 `pytest -q tests/test_collaboration_console.py tests/test_console.py tests/test_collaboration_events.py --junitxml=.runtime/p12-b3-evidence/final-ui-events.xml`，得到 **15 passed in 40.15s，0 failed / 0 errors / 0 skipped**，验证当前 UI 与事件接口；两次运行不相加冒充一次217测试。Ruff：`All checks passed!`；`git diff --check` 和 `git diff --cached --check` 无错误。本批没有运行全仓 pytest、live 测试、wheel HTTP 发布 Gate 或云端验收。

## 双身份配置与本地自检

生成新的演示目录：

```powershell
.venv/Scripts/python.exe scripts/prepare_collaboration_demo.py
```

默认目录名包含时间和随机后缀，也可 `--output .runtime/<新的目录>`；已存在目录立即拒绝，不能覆盖。脚本生成一个包含两份独立 grant 的共同服务配置，以及两个各含本人 grant 的客户端配置；客户端不应选择共同服务文件。模式 scripted_double，事实沿既有 `perception-v1` SYNTHETIC 夹具复制到新租户，ID 来自原 refs.json，时钟明确为合成回放时间 `2026-09-22T04:00:00+00:00`。脚本不写任务、checkpoint、预算或旧私聊，不打印 token。

本次保留的私密路径：

- `D:\src\agent学习\安澜2.0\.runtime\p12-b3-demo\service.json`（共同后端，只用于启动服务）。
- `D:\src\agent学习\安澜2.0\.runtime\p12-b3-demo\applicant.json`（申请人客户端）。
- `D:\src\agent学习\安澜2.0\.runtime\p12-b3-demo\safety-manager.json`（安全人员客户端）。

启动（使用上面的本地测试库环境；不打印 DSN）：

```powershell
.venv/Scripts/python.exe -m anlan.interfaces.serve --config .runtime/p12-b3-demo/service.json --port 8013
```

分别在两个隔离浏览器上下文打开 `http://127.0.0.1:8013/console`，选择各自客户端文件。原脚本语法亦可复现：“提交申请给 safety-manager-demo”“要求补充：具体要求”“重新提交申请：补充说明”“完成材料核查：人工说明”，每步再明确确认；申请人补材料沿原字段补充流程。

本地点击自检使用两个独立 context 和上述两份配置，同 task `0a39303c-e462-5c12-92b4-2a42c735594e`，申请人会话 `09dcade1-5797-43da-be7f-edfb2f1ebf51`，安全人员会话 `408594a4-47e0-4e6a-81a1-a600f681a665`。实际点击提交→要求具体点位→本人补充材料至 revision2→重提→人工材料核查完成，application version=5，completed_material_revision=2。还点击了一条合成事件核查和 needs_verification 反馈，原报警仍 active。

自检覆盖桌面1440×1000及390×844，横向溢出检查为false，安全人员无新建材料入口，完成后无协作写卡片；跨轮询草稿实际保留。协调两项修复后重启本地服务和页面，再核对申请人 offline_not_checked、安全人员共享投影，以及申请人访问对方私人会话404。截图/无凭据摘要在 `.runtime/p12-b3-evidence/manager-mobile*.png`、`applicant-desktop-complete.png`、`manager-event-feedback.png`、`local-browser-summary.json`。最终源码的额外申请人截图工具未返回，已取消该可选截图并保留之前截图，未冒充生成文件。自检发现的问题均先补 RED 再修复；过程中模拟窗口模式改变会重载页面，需要重新选择配置。截图是开发自检，**不代替 B4 对最终提交的独立双端/恢复验收**。自检进程和本人创建的两个浏览器上下文已关闭，PG 与配置/业务记录保留。

浏览器自检为避免加载嵌入模型，显式注入 `UnavailableKnowledgeStore`：固定事实两项返回 ok，知识检索返回未知并在 evidence_gap 保留，模型为 scripted_double。脚本只准备事实与访问配置，不把旧租户知识库或私聊自动共享到新租户；若需演示知识命中，应沿既有知识导入流程准备该新租户的合成知识。默认 serve 的知识库组合保留，邻接 HTTP/核查测试覆盖其原流程。

## 遗留与下一批

本批不宣称全流程云端验收或生产系统完成。B4 仍须全仓、最终版本双浏览器/进程重启/断网恢复、wheel/发布 Gate；B5 才能按原账本做有限真实模型、部署和双角色视频。列表/时间线有界100、页面通知缓存200、草稿仅当前页面内存，刷新不会恢复未提交草稿；持久化业务记录与确认卡片会恢复。没有 SSO、正式审批、作业许可或报警控制。

协调已只读提出两项修复意见，本交接记录其实际 RED/GREEN；本会话没有另派审查代理。待协调读取本提交并独立验收后，才串行启动下一批。
