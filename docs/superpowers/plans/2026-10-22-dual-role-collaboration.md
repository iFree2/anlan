# 安澜双角色材料核查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use executing-plans, test-driven-development and verification-before-completion inside each user-requested batch conversation. Do not create further threads or delegate work without explicit authority. Execute the five batches serially in the existing local checkout, never concurrently.

**Goal:** 申请人与安全人员独立身份/独立会话，以同一task_id完成提交→要求补充→补充/重提→人工材料核查完成，并部署和录制。

**Architecture:** 保持原材料Graph与会话私有归属，新增协作合同、服务端角色、显式任务参与权限、PG状态/审计/收件箱。重要业务动作经持久化确认候选后执行；前后端共用真实状态与版本，不复制材料、不冒用申请人Identity。终点只到材料核查完成。

**Tech Stack:** Python3.13 / Pydantic / FastAPI / PostgreSQL / LangGraph / 现有HTML/JS/SSE；模型替身完成开发验证，最终有限DeepSeek云端联调；Edge TTS与FFmpeg复用视频流程。

---

## 公共约定与执行方法

完整阅读已确认spec、P12验收清单、本计划，再读本批文件。每个实现单元遵循：先写下列具名失败测试，运行验证失败原因；做最小实现；重跑测试与Ruff；只提交本批路径。不得以PG测试skip称通过。

```powershell
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
.venv/Scripts/python.exe -m pytest -q <本批明确列出的测试文件>
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
```

测试使用本地独立PG17，不连接云端数据库；脚本输出不得打印DSN。真实请求仅B5，累计100、对话P11-WP01=30、材料/事件P11-WP02=10不变。无新包/扩额授权。所有批次交接必须记录提交哈希、文件、红绿命令与结果、PG是否实际运行、遗留项/下一批接口。

保留原有用户dirty路径，禁止git add -A、reset/checkout恢复、不把迁移编号012挪用。增量迁移从017开始。B1-B4不改云端、不SSH、不运行live tests。当前基线源码59093b8，文档交付91604c7；不能用旧586测试结果替代本批验证。

## B1：可信角色、领域合同、权限策略与PG存储

**负责文件：**新建 `src/anlan/collaboration/__init__.py`、`contracts.py`、`policy.py`；新建 `src/anlan/infrastructure/collaboration.py`、`src/anlan/sql/017_collaboration.sql`；修改 `interfaces/service_config.py`；新增 `tests/test_collaboration_policy.py`、`test_collaboration_store.py`、`test_collaboration_config.py`、`docs/phases/phase-12-dual-role/batch-01-handoff.md`。本批不接HTTP/Graph/前端，不放开现有owner权限。

- [ ] Step 1：添加配置RED测试：显式applicant与safety_manager可解析；legacy缺省None；同tenant/user矛盾角色、客户端字段注入、不合法角色拒绝。运行 `pytest -q tests/test_collaboration_config.py`，预期缺少角色合同而失败，不能为环境错误。
- [ ] Step 2：按以下固定领域接口添加policy RED测试，覆盖每个角色×状态×动作，以及跨租户/未分配/自核查拒绝：

```python
# contracts.py 的公共命名合同；具体严格模型按spec构造。
Role = Literal['applicant', 'safety_manager']
ApplicationStatus = Literal['draft', 'under_review', 'changes_requested', 'review_completed']
Action = Literal['read', 'edit_materials', 'submit', 'request_changes', 'resubmit',
                 'complete_review', 'read_events', 'run_event_review', 'record_event_feedback']
# ApplicationRecord: task_id, tenant_id, applicant_user_id, reviewer_user_id|None,
# status, version>=1, submitted_material_revision|None, completed_material_revision|None.
# authorize(actor: Identity, role: Role|None, application: ApplicationRecord, action: Action)
# 成功返回None；无资源权限AccessDenied；非法阶段InvalidTransition。
```

确定性要求举例：applicant+draft+edit_materials允许；applicant+under_review+edit_materials冲突；assigned safety_manager+under_review+complete_review允许进入命令验证；同租户unassigned safety_manager+read拒绝；任意角色无法读取另一人的conversation。后者原会话测试回归而不是开放新接口。

- [ ] Step 3：实现严格合同和纯权限策略，再按上述policy/config测试逐项绿灯。TokenGrant增加 `collaboration_role: Role | None = None`，ServiceConfig提供 `collaboration_role(identity)` 与同租户reviewer名单（不暴露token）；配置查找和矛盾校验由服务端完成。
- [ ] Step 4：添加真实PG RED测试：`test_ensure_draft_preserves_task_owner_and_is_idempotent`、`test_assigned_visibility_and_cross_tenant_denial`、`test_reconnect_and_repeat_initialize_preserve_old_rows`。使用已有 `test_events_postgres.dsn/run` fixture及OfflineAnalyzer创建真实task，不假造无归属task。确保迁移未存在时失败。
- [ ] Step 5：实现CollaborationStore(dsn).initialize、ensure_draft(actor,role,task_id)、get(actor,role,task_id)、list(actor,role)。ensure_draft必须先核对原registry的tenant/user，不接受任意owner；schema中collaboration_applications主键task_id关联原task。commands以tenant/actor/request_id唯一；events记录真实actor/revision/version；notifications带recipient与event_id唯一约束，全部显式schema、有界文本和索引。先只实现初始化/注册/读取；B2才对外启用命令。
- [ ] Step 6：执行并记录实际结果：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_config.py tests/test_collaboration_policy.py tests/test_collaboration_store.py tests/test_conversation_store.py tests/test_service_api.py tests/test_package_layout.py
.venv/Scripts/python.exe -m ruff check src tests
```

验证wheel SQL资源规则不硬编码旧数量；确需更新打包断言时记录原因，不删旧迁移校验。交接B2所需表字段/函数签名与锁方案；只提交B1文件及必要相邻测试，不开始B2。

## B2：共享业务授权与可恢复协作命令

**负责文件：**新增 `collaboration/service.py`、`collaboration/access.py`、`interfaces/collaboration_routes.py`；扩展store及新 `tests/test_collaboration_service.py`、`test_collaboration_api.py`；按需要修改 `workflows/service.py`、`workflows/registry.py`、`infrastructure/postgres.py`、`interfaces/runtime.py`、`interfaces/api.py` 的授权/事务/注入，不整文件重写；新增batch-02-handoff。

- [ ] Step 1：实际读取B1交接和commit，先写RED：`test_submit_return_resubmit_complete_same_task`。用两个真实Identity、两独立HTTP clients、同task进行完整往返，断言材料task_id不变、版本递增、actor是安全人员而非申请人、review_completed不是approved。
- [ ] Step 2：写RED：未分配/跨租户读取拒绝；申请人尝试complete被拒；安全人员改材料被拒；applicant直接旧 `/tasks/{task}/resume|revise|recover` 及Graph入口不能在under_review或completed写入；legacy任务保持private。不能为通过测试把所有同租户用户都当参与者。
- [ ] Step 3：实现公共TaskAccess边界：读取原owner和已授权参与关系，以真实actor评估动作；shared read用白名单投影，owner作为资源索引不代替actor。无协作的legacy任务保持原权限。对新角色start创建draft，崩溃后ensure_draft可重入；安全人员不能start申请。检查所有现有HTTP和会话适配器，不只检查新URL。
- [ ] Step 4：按spec实现以下命令接口（role/actor来自认证，不出现在payload）：

```text
GET  /collaboration/applications
GET  /collaboration/applications/{task_id}
POST /collaboration/applications/{task_id}/commands/submit
POST /collaboration/applications/{task_id}/commands/request_changes
POST /collaboration/applications/{task_id}/commands/resubmit
POST /collaboration/applications/{task_id}/commands/complete_review
GET  /collaboration/notifications
```

四个POST均包含 `request_id, expected_application_version, expected_material_revision`。submit另含reviewer_user_id；request_changes含非空questions列表；resubmit含非空reply；complete_review含非空conclusion。使用各自StrictModel，禁止多余字段。新接口先可做确定性调用，B3才接对话确认；HTTP本身仍须校验全部权限/版本。

- [ ] Step 5：写并通过 `test_command_replay_and_payload_conflict`、`test_transaction_failure_has_no_partial_notification`、`test_concurrent_edit_and_completion_conflict`、`test_pending_material_recovery_cannot_finalize`。共用task锁核查checkpoint及pending，命令事务同时持久化状态/事件/通知/回执。不得将模型调用和协作提交伪装成一个不存在的原子事务。通知只含允许共享信息、仅给对应收件人。
- [ ] Step 6：在 `api.create_app` lifespan接协作初始化，增加 `/console/api/info` 的可信role与能力标记，不返回token；返回错误沿用401/404/409/422合同，不暴露资源存在或私密异常。
- [ ] Step 7：运行 `pytest -q tests/test_collaboration_policy.py tests/test_collaboration_store.py tests/test_collaboration_service.py tests/test_collaboration_api.py tests/test_postgres.py tests/test_material_revisions.py tests/test_service_api.py tests/test_service_reliability.py tests/test_conversation_api.py`，Ruff通过后交接提交；列出尚待B3接入的会话和事件路径，不宣称已双角色UI可用。

## B3：双角色对话、待办、通知与事件核查

**负责文件：** `conversation/contracts.py`、`policy.py`、`service.py`、`llm/conversation.py`、`infrastructure/conversations.py`、`interfaces/conversation_runtime.py`、`console/routes.py`、`console/service.py`、`interfaces/perception_runtime.py`及事件/核查store授权边界、console assets；新增 `tests/test_collaboration_conversation.py`、`test_collaboration_events.py`、`test_collaboration_console.py`；新增 `scripts/prepare_collaboration_demo.py` 和batch-03-handoff。

- [ ] Step 1：先写RED对话测试：申请人submit候选不提交，确认后只提交一次；安全人员request_changes候选不通知，确认后申请人本人会话显示业务要求；resubmit与complete同样先确认。reject、闲聊、普通引用“确认”、过期卡片均不能写业务。候选需冻结完整命令/双版本与目标人，不让LLM确认时改字段。
- [ ] Step 2：角色感知模型上下文只包含本人私聊、合法共享材料/业务事件、允许动作。确定性策略二次校验角色/状态/版本。不得让安全人员走申请人START_HOT_WORK/SUBMIT_TASK_INPUT。阅读/待办/选单可直接结构化，避免为列表重复付费。
- [ ] Step 3：实现本人会话安全绑定共享task，新增业务通知投影/认证快照更新。两个conversation_id不同但task_id相同；不要把对方private messages复制到通知，也不要因另一端进度变化暴露对方会话ID。通知event_id稳定，刷新和恢复不重复插消息，离线补读。
- [ ] Step 4：先写并通过事件RED：只有指定安全人员可模拟/发起核查/记人工反馈；两参与者按受限共享结果读取；同租户未分配角色与跨租户不可读取receipt/review。核查与反馈audit记录真实安全人员actor；不能简单用ownerIdentity调用旧API跳过权限。新材料版本使旧核查过期，原报警保持active。
- [ ] Step 5：UI显示可信角色，左侧本人会话/待办，中间本人对话与共享业务卡片，右侧共享申请状态/版本/时间线。按钮按服务器能力展示，不能仅前端控制权限；申请人无安全人员操作，管理端不出现改材料入口。页面显示“材料核查完成≠作业批准”。移动端390×844可展开操作。新连接配置清理旧身份内存/流/缓存，不能串号。
- [ ] Step 6：演示准备脚本生成两份独立私密配置与一个共同后端配置，模式scripted，默认写新路径不覆盖，禁止打印令牌。模拟人员/区域保持SYNTHETIC。若为schema增加确认记录另用018，不重写已发布017，不动012。
- [ ] Step 7：执行新增三测试及 `tests/test_conversation_policy.py tests/test_conversation_model.py tests/test_conversation_service.py tests/test_conversation_api.py tests/test_console.py tests/test_perception_postgres.py tests/test_service_http.py`，通过Ruff后提交并交接可复现双身份启动命令。

## B4：集成Gate、双浏览器与恢复

**负责文件：** 新增 `tests/test_collaboration_recovery.py`、`test_collaboration_release.py`、`scripts/verify_collaboration_release.py`、P12 evidence及batch-04-handoff；发现实现问题仅作与本期相关的最小修复并记录red/green。

- [ ] Step 1：先增加恢复/并发RED，覆盖写回执前中断、通知事务回滚、双端旧版本卡片、重复确认、offline重连、actor撤权、同租户第三者、跨租户第三者、私聊哨兵不进对方响应/模型上下文。restart使用新进程而非只构造新对象。
- [ ] Step 2：用两个独立浏览器上下文与不同token真实点击完整往返；页面同时显示同一申请编号和独立会话。保存隐去凭据的截图/步骤结果；验证事件核查及反馈、桌面与移动端、断线后收件箱去重。浏览器实际错误不得只改报告为passed。
- [ ] Step 3：运行完整 `pytest -q`，实跑PG、不跳过；Ruff检查src/tests/evals/scripts/deploy。构建wheel、校验新SQL/静态资源；离源码目录运行wheel服务并重启恢复。脚本不得默认live或触云端。
- [ ] Step 4：证据记录准确测试数/跳过/失败、源码commit、wheel SHA、双端身份代号/同task/两个conversation、已知限制。逐条更新P12清单，有未满足项不得通过到B5。不把工程通过表述为生产安全/模型泛化。

## B5：云端替换、有限live与双角色视频

**负责文件：** `deploy/aliyun/release_conversation.py` 的兼容更新或独立 `release_collaboration.py`、对应deployment tests；P12 deployment/evidence/narration与ignored媒体。只在B4 Gate通过后创建本批会话。

- [ ] Step 1：通过现有私密SSH文件和主机指纹连接，先只读检查current/systemd/旧行摘要/预算/配置，不打印秘密。备份DB与配置到0700/0600目录，上传校验wheel。读取当前真实预算，不使用历史79/100冒充当前值。
- [ ] Step 2：准备新版双身份私密配置，不把原演示token擅自提升为双角色或分享旧记录。保留旧版，验证新协作数据存在时回滚只读/维护能防旧接口写入；不回滚DB/账本，不改原站点。备份、预检完成才短时切换应用并检查就绪。
- [ ] Step 3：本次最多8次对话调用、4次材料分析、1次事件核查，共13次真实尝试；同时受各包和累计剩余额度约束。调用前计算最小所需；不足先停并请求用户授权，不开启新包、不隐式重试。复用一次合成申请链录制，失败照实保留计数。
- [ ] Step 4：两个真正独立的认证浏览器上下文完成申请人提交→安全人员要求具体位置补充→申请人更新/重提→安全人员显式材料核查完成，双方显示相同task；根据预算演示一条合成事件核查/反馈。发布后重启再确认状态恢复、旧行/原站点不变。
- [ ] Step 5：重录真实云端两角色画面，用明确角色标识和同申请编号切镜，不剪成同一身份代理两人。保留用户已选女声 `zh-CN-XiaoxiaoNeural`、rate=-10%、pitch=-4Hz及口语文案；按新流程写原创旁白、重新生成字幕。媒体另存新目录，原两版不覆盖。
- [ ] Step 6：完整解码H.264/AAC、检查逐章非静音、字幕与文案一致、业务关键帧及结束边界，记录SHA/时长；交付新入口、两份私密配置路径和视频。更新P12总交接，保留未实施SSO/TLS/正式审批/真实现场等限制，不泄露凭据。

## 批次启动与验收责任

协调会话负责创建每个独立会话、读取其交接/commit、独立运行必要测试、确认Git未夹带用户改动并更新P12 README状态。前批未过不派发后批；不预先启动五个会话并发实现。各批不自行创建后续任务或重启旧任务。本期全部验收和视频完成前不宣称整个交付完成。
