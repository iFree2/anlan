# P10 人员三能力受控增量设计

2026-11-22。状态：总窗口已于2026-11-22批准设计门禁；人员三能力已进入实现与本地验证，零模型调用。

## 范围与方案

首包只做 contractor.qualification.query、person.training.query、person.access.query。作业票 ticket/overlap 留待本包接口和端到端验收稳定后另审，不把合同已有视作业务链完成。

推荐新增 personnel.py 宿主策略/请求/冻结快照，以及 external_inquiry_personnel.py 独立装配。复用冻结的 build_dynamic_definitions、ToolPolicy.bind_task_grant、ToolExecutor、SDK 和 InquiryAuditStore；不新增直通调用。备选方案为抽公共设备工作流（需要改冻结接口，本包不采用），或先做纯合同（无法满足受控端到端，因此不推荐）。独立工作流沿用设备循环边界，避免修改设备实现；重复循环是本包明确代价，后续统一抽取须另审。

## 可信身份与对象解析

宿主配置包含 tenant、策略版本、厂区目录版本、承包商和人员目录版本、对象关系与用户 grant。请求只带任务、厂区别名、承包商/人员显式 ID 或名称、资质类别、培训类别与问题，不接受身份、URL、命令或凭据。

先 service.get 验任务，再验证 identity/tenant/user；厂区别名未知或歧义拒绝。承包商和人员名称仅按宿主目录精确解析，候选多于一条必须显式 ID，不以用户授权过滤重名候选来静默消歧。显式 ID 必须存在且名称（如提供）一致。宿主目录明确人员所属承包商及厂区；关系不一致拒绝。grant 分别限定厂区、承包商 ID、人员 ID、资质类别、培训类别及三能力；不把两类对象的笛卡尔积视为真实雇佣关系。

资质请求 objects=[contractor_id] 且 category 为显式已授权资质类别；培训 objects=[person_id] 且 category 为显式已授权培训类别；准入 objects=[person_id]。三能力不可替代，不从培训推导准入，不从承包商资质推导个人培训。准入只读，绝不写授权。

## 同一执行边界

按人员三能力和唯一厂区 load_catalog，校验 tenant/reader/entry 范围和 alias 唯一，缺能力或竞争来源拒绝。每能力只选唯一来源；每 alias 固定规范 CapabilityRequest JSON，并提前冻结完整 CatalogLease。快照提供现有 execution 所需 identity/task/run/correlation/revision/query_at/catalog/entries/requests/leases/task_grant 属性，不假装设备对象。

循环使用同一冻结 TaskCatalog 给模型与 Executor；host.authorize 在 execution 原有分发/发布阶段重检。继承 SQL023 发布共享锁、代次、凭据与策略重检。普通对话/操作台不装配，不改 SQL/主 initializer，不写真实企业数据。

## 结果和失败

报告标识 personnel 三能力及人员/承包商 ID，分别保留 observed/missing/partial/unknown/unusable；contractor/training/access 状态逐条原样呈现，completed 只表示本轮观察齐全，绝不是安全/合规/准入结论。候选必须标记 unverified_candidate，引用仅限本轮已发布证据。unknown、空/partial、next_cursor 和失效时间均保留；不自动翻页、重试或换源。模型正文及工具内容不授予权限。

继承最多3模型轮、attempt/wire各6、父60秒、handler5秒、32KiB输入、64KiB结果、跨轮 call_id 去重与同步截止；取消清理有独立窗口，不承诺总墙钟严格等于业务截止。

## 小计划与验收

1. 先测试可信对象目录解析、重名显式ID、跨承包商/厂区/类别越权、厂区别名与竞争来源拒绝、快照冻结；运行 RED 后最小实现 GREEN。
2. 使用既有执行器装配人员循环和零付费 scripted 模型，测试能力分离、参数篡改零 wire、unknown/partial/无来源/引用/预算边界；每项保持 RED/GREEN 证据。
3. 新增合成 stdio 人员服务；真实本地 SDK + 隔离 PG 管理/发现/启用/三实际 tools/call/三个 receipt 及任务不变端到端，与纯 scripted 单测分开报告。
4. 请求独立审查，修复 critical/important；串行人员定向及受影响设备/合同/执行/旧工具回归、Ruff、diff 检查。PG 凭据只在进程内使用，无 live/SSH/部署。
5. 写 report.md、证据和独占文件清单，停止，交总窗口复验和统一发布。禁止 stage/commit/reset/clean/切分支。

## 所有权与待审项

仅新增/修改任务授权的 personnel.py、external_inquiry_personnel.py、dynamic_personnel_model.py、test_dynamic_mcp_personnel*.py、新 fixture、examples/synthetic/dynamic-mcp-v1/** 和本包目录。当前不需要 permit.py。冻结核心文件不改。

设计门禁已确认：总窗口明确批准首包边界、可信目录关系和独立工作流方案，无需另等用户。若发现执行器对人员合同不兼容，记录最小复现和所需接口变更，停止等待总窗口协调。
