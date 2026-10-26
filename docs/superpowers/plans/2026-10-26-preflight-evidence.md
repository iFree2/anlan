# P13 Preflight Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans with TDD and verification-before-completion. 用户已明确“实施”；按既有偏好各批独立local会话、同检出串行、不创建worktree。协调负责验收，不与实施会话并行改代码。

**Goal:** 在提交/重提后自动完成绑定本申请人员/区域的作业前证据预核查，当前有效依据与人工引用确认是材料核查完成的必要条件。

**Architecture:** 独立对象绑定/策略/任务/结果持久化，复用task授权锁、FactTools/KnowledgeStore和协作通知。后台仅做只读查询与确定性摘要，不额外调用LLM。完成、重提、事件核查分别绑定当前材料/对象/依据版本；无跨角色私聊共享或正式审批。

**Tech Stack:** Python3.13、Pydantic、FastAPI、PostgreSQL、原生JS、既有wheel/双浏览器验证。

设计：[2026-10-26-preflight-evidence-design.md](../specs/2026-10-26-preflight-evidence-design.md)；验收：[P13](../../phases/phase-13-preflight/acceptance.md)。用户2026-10-26“实施”确认了书面设计；首版单人员/单资质类型/单区域。

## 0. 共用执行纪律与接口

基线f103490。原用户dirty：docs/roadmap.md、docs/status.md中P10段落、docs/phases/phase-10-dynamic-mcp/、tests/test_tool_loop_live.py、.superpowers/。保留，不git add -A/reset/checkout。文本用apply_patch。每批红→绿、实际本地PG、Ruff、提交、handoff，经协调审查通过后才启动下一批；不提前创建四个会话。

本地用项目PG17/127.0.0.1:55432的新隔离库，例如anlan_p13_b1_20261026；scripts/dev-postgres.ps1 -Action Env后只替换库名，不输出DSN。测试不读取云端凭据、供应商key，不跑live_model。旧“100次”限制已被用户取消，现为audit_only；不重置/重新启用限额。不以无限项目次数为由进行付费自测。

SQL019用于对象绑定与逐申请策略，SQL020用于任务/执行尝试/结果；如确需新增迁移沿后续编号，不改已发017/018或保留012。不默认开启尚未实现的半套门控。

跨批公共合同命名如下，B1提交时可按实际代码细化字段并在交接记录，后批不得另造同义版本：

```python
# src/anlan/preflight/contracts.py，全部StrictModel，actor/role不来自HTTP。
# BindingCommand: request_id, expected_material_revision>=1,
# expected_binding_revision>=0, worker_id, qualification_type, area_id
# BindingRecord: task_id, binding_revision>=1, material_revision_at_confirmation,
# references: FactReferences, confirmed_by: Identity, confirmed_at
# PrecheckPolicy: task_id, required, legacy_completed
# EvidenceKey: task_id, material_revision, binding_revision, application_version
# 预核查执行状态与业务assessment/currentness独立，不能把outcome=ok等同ready。
```

目录首版使用服务器配置 `precheck_catalogs`，按租户提供带标签的workers（含允许qualification_types）与areas，默认为空。可见项必须与现有facts access授权相交；目录仍可包含获授权但事实记录缺失的对象，以便显示真实缺口。目录不凭模型生成，也不把安全人员console profile作为默认绑定。原TokenGrant/Identity保持。

## B1：可信目录、绑定合同、权限与PG存储

**Ownership:** 新建preflight/__init__.py、contracts.py、catalog.py、bindings.py、infrastructure/preflight.py、sql/019_preflight_bindings.sql；扩展interfaces/service_config.py；新tests/test_preflight_contracts.py、test_preflight_catalog.py、test_preflight_bindings.py、test_preflight_store.py及batch-01-handoff。必要相邻配置/打包断言可最小调整。本批不接HTTP/UI，不做自动查询，不改协作完成规则，不改云端。

- [ ] 写RED合同与目录测试，断言缺省目录兼容、跨租户/不可见ID拒绝、同租户两组不同对象可列选、普通姓名不当ID、未知角色/actor字段拒绝、布尔版本拒绝、空标签/目录重复冲突拒绝。示例：

```python
def test_binding_command_keeps_resource_ids_separate_from_actor():
    from anlan.preflight.contracts import BindingCommand
    command = BindingCommand(request_id='bind-1', expected_material_revision=1,
        expected_binding_revision=0, worker_id='worker-a',
        qualification_type='welding', area_id='area-a')
    assert command.worker_id == 'worker-a'
    assert 'actor' not in command.model_dump()
```

- [ ] 运行pytest -q tests/test_preflight_contracts.py tests/test_preflight_catalog.py，确认因新能力缺失而RED；实现严格合同、配置和授权目录，复用AccessData只在服务端筛选。无法读授权源即fail-closed，不退回全目录。
- [ ] 添加真实PG RED：原owner创建的实际材料任务下确认绑定，GET/重连保持、同request同载荷幂等、变载荷/跨task request冲突、不正确material/binding revision拒绝、安全人员/第三者/跨租户/撤权拒绝；draft/changes_requested允许，under_review/completed拒绝修改。用现有OfflineAnalyzer/registry而非伪造材料行。
- [ ] 实现BindingService(dsn,config,service_context_factory).catalog(actor,task_id)、confirm(actor,task_id,payload)、get(actor,task_id)。confirm必须在原registry授权task锁下读真实checkpoint/未完成提交，核对双版本与角色后在同PG事务写不可变binding版本、head、命令回执。跨task actor/request命名空间用独立前缀事务锁。无变化的重新确认不虚增binding revision。
- [ ] PrecheckStore.initialize创建独立policy、binding_heads、binding_versions、binding_commands表；同task外键、唯一版本与命令键，显式tenant约束。不向原四字段写入worker或actor。ensure_policy保持旧已完成legacy标记，旧未完成required；重复初始化不覆盖后续结果，不迁移私聊/账本。B1仅通过新store显式初始化，尚不激活旧HTTP流程门控。
- [ ] 跑新增四测试及test_collaboration_config.py、test_collaboration_store.py、test_service_api.py、test_package_layout.py、test_demo_short_tokens.py，全部使用本地隔离PG；Ruff check src tests evals scripts deploy。交接实际public接口、表名/字段、权限与锁、红绿数/运行命令、未接入项，提交本批文件。

## B2：持久化自动预核查、当前性与完成门控

**Ownership:** 新preflight/evaluator.py、service.py、runner.py、infrastructure/preflight_jobs.py、sql/020_preflight_checks.sql；扩展collaboration/service.py、binding/store、API lifespan/ServiceModels装配（不改页面）；新test_preflight_evaluator.py、test_preflight_jobs.py、test_preflight_service.py、test_preflight_gate.py；batch-02-handoff。需要调用现有工具时维持真实actor，不冒用owner。

- [ ] 读B1实际交接；先写纯评估RED：active+normal+有效知识候选可供人工审查，suspended/revoked、restricted/closed、unknown/error、过期/撤回/无引用不可ready；校验引用与当前查询ID，不仅看三项ok。摘要不能调用模型。
- [ ] 写真实PG提交RED：同一协作提交事务同时产生状态/通知/唯一预核查job，save_receipt前失败全部回滚；重复确认/重连不重复job。提交缺少可信绑定被拒绝，under_review仍可读/要求补充，不因工具异常阻断补充。
- [ ] Job持久化EvidenceKey、真实发起人、refs/材料安全快照、requestid、执行状态/lease/attempt和不可变结果。领取与结果保存短事务；源查询在锁外。租约用真实PG时钟，证据有效性用配置业务时钟（固定回放不能让租约永不过期）。恢复过期lease留尝试记录，0新增付费请求。
- [ ] runner使用当前对象的两个FactTools和基于作业对象/方式的KnowledgeStore查询，三结果汇合保留来源/引用/截止期。不得调用DeepSeek，不用固定告警知识问题。正常输出有效截止为min(业务时钟+10分钟,各来源截止)，来源unknown则记录缺口。
- [ ] 写旧结果/并发RED：换材料/绑定/申请版本、来源更新/知识撤回、授权撤回、证据过期、旧job晚回写，均不能覆盖新结果或用于完成；完成在task锁下核对当前元数据和人工引用集合，不在GET刷新重跑工具。
- [ ] 扩展提交/重提/完成冻结载荷：expected_binding_revision及完成expected_check_id/采用引用集合。旧卡片缺少新字段时在required任务受控409，不确认时偷换新版本。直接HTTP、conversation adapter、旧组合都通过相同持久化门控，无客户端override。
- [ ] 重提支持材料或绑定实质变化；源资料修复可先重查，再凭变化的来源证据批次重提，无需修改无关材料。重复查询不伪增材料版本。人工结论不能使unknown或异常变ready。
- [ ] HTTP应用新任务ensure_policy/绑定缺口，新版启动对旧未完成协作任务明确required、旧已完成legacy；旧private不共享。无迁移状态或新策略缺失不能让新任务静默沿旧完成路径。原P12测试fixture应显式表达其legacy/新策略语义，不靠全局关掉门控“保绿”。
- [ ] 跑B2测试及B1、test_collaboration_service.py、test_collaboration_api.py、test_conversation_api.py、test_service_reliability.py、test_audit_only_budget.py，非live、真实PG；Ruff。真实新进程验证queued/running恢复，留证据与handoff，提交。

## B3：双角色页面、明确操作与事件复核引用

**Ownership:** 新interfaces/preflight_routes.py；扩展collaboration_conversation.py、conversation contracts/freeze、console assets/routes/service、perception_runtime.py、event_access/SourceBinding必要兼容字段；更新scripts/prepare_collaboration_demo.py或新prepare_preflight_demo.py；test_preflight_api.py、test_preflight_console.py、test_preflight_conversation.py、test_preflight_events.py；batch-03-handoff。

- [ ] RED并实现固定接口：GET /collaboration/applications/{task}/object-catalog、GET/POST .../binding、GET .../prechecks、POST .../prechecks（显式重查，request_id、双版本、非空reason）。身份来自who；不得传任意URL、SQL、actor、ready。服务端角色/阶段/版本校验，不依赖按钮禁用。
- [ ] 页面新增绑定选单与确认、作业前依据卡片、当前性、来源时间/摘要/知识引用和异常解释，明确ready非批准。新按钮确定性结构化动作，0分类器请求；不用一段闲聊冒充工具调用。现有重要协作卡片冻结完整新版本/引用。
- [ ] 按角色/状态显示操作，目录空提示“未配置/无授权对象”不默认选择；两窗口可共享当前证据但不能见私聊。身份切换/迟到响应/轮询不串号，保留其他表单草稿。新增UI测试实际跑JS行为，不只检查字符串。
- [ ] 事件生成与核查从申请已确认binding取worker/type/area，console profile只表达权限。信任绑定增加binding_revision，旧contract可只读，换binding的旧review标stale_binding；材料变化仍stale_material。预核查不ready不能吞原报警，不自动清警。
- [ ] 制作两组不同的公开合成目录/事实/知识，显式授权两角色，包含异常与缺失；输出新路径不覆盖用户私密访问配置。不复制旧租户私人知识，不打印令牌。
- [ ] 跑B3+B1/B2及test_console.py、test_collaboration_conversation.py、test_collaboration_events.py、test_perception_postgres.py、test_demo_short_tokens.py，Ruff。实际双浏览器演练绑定→提交自动查询→缺口/补充→重查/重提→人工引用确认/完成→事件新对象，交接提交。

## B4：本地集成Gate与可部署交付

**Ownership:** 新test_preflight_recovery.py、test_preflight_release.py、scripts/verify_preflight_release.py、P13证据/交接/演示脚本；只做相关最小修复。可复用已审查的loopback限定/实际serving PID/受限temp cleanup防护，不能复制出无效目标校验。

- [ ] 先增加真实故障/恢复RED：提交后浏览器断开、worker领取后退出、工具执行时源/绑定变化、结果回写前中断、完成前来源失效、双端旧卡片、提交/绑定/完成竞争、撤权缓存、第三者私聊哨兵。
- [ ] 完整pytest -q -m 'not live_model'，准确报告排除数与失败；用户未提交live测试不得运行。全目录Ruff、wheel构建/SQL资源/离源码和实际服务进程重启恢复。新源码测试不能用旧905结果替代。
- [ ] 两独立浏览器/不同Identity/同task，至少正常与资质异常、区域受限、知识缺失、换人/区域、源修复场景；人工不确认引用/过期引用不能完成，补充与重查可继续。桌面与390×844、断线/刷新、重启检查，保存无凭据证据。
- [ ] 更新P13逐条验收、handoff和新手脚本，标记真实能力/固定时钟/合成数据与未实施项。保留旧视频，不编造新演示证据。
- [ ] 交付本地验证制品及部署方案。**本次先执行本地开发与验收；不SSH、不真实模型调用、不更换线上版本或录制新的付费实录。** 云端发布/实录另在Gate后确认执行范围；取消项目次数上限不改变此边界。

## 协调检查点

每批结束只读核对实际commit/文件/证据，再运行独立必要测试、请求只读代码审查，Important关闭后才派下一批。协调只维护阶段README/acceptance/coordinator-check，实施者只写自己的handoff/证据，不自行启动下批或给其他会话发消息。中断回原批次续做，不创建重复会话；未整体完成时不得称“全部好了”。
