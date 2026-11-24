# M3 最小动态设备查询链详细设计

日期：2026-11-17。状态：**D审查通过，以下补充已冻结，按TDD实施设备三能力首链。**

前置：T1/M1与M2已交付；M2最终定向198 passed、Ruff通过，报告见dynamic-mcp-registration-report.md。本设计只闭环用户优化4的首条动态设备业务链，不把注册/发现或协议测试当作业务调用完成。

## 1. 目标与最小范围

可信企业厂区别名/明确设备ID → 宿主授权与单来源决策 → 冻结任务目录 → scripted模型提出工具动作 → **同一本地ToolRegistry/ToolPolicy/ToolExecutor** → 受信SDK call_tool → M1业务绑定 → 当前禁用/代次二检 → 可追溯辅助证据。

首包完整覆盖equipment.asset.query、equipment.inspection.query、equipment.fault.query三项设备能力；其余五项人员/票据合同保留，M3首包不声称完成其端到端。只运行scripted零付费与真实本地合成SDK stdio/HTTP，不调用真实模型/企业系统、不部署。

选择：不在M2 RuntimeManager上加公开call；不建另一套绕过T1的执行循环；新增仅供本地Executor装配的动态handler，扩展T1 Policy的可信任务grant入口，复用原Registry与Executor。旧固定事实/知识loop、预算与P13确定性链保持原行为。

首包不实现跨系统映射、时间分工/替代/双源投票、备用源或自动翻页。未取全列表明确partial，不能解释为无故障；自动分页留后续独立增量，避免首包把同一任务目录中的cursor权限隐式扩大。

## 2. 可信输入与企业路由

`InquiryRequest(task_id, factory_alias, equipment_id, question)`来自用户；全部仍是不可信业务输入，不能携带tenant/user/service/URL/command/credential/config版本或授予范围。`WorkflowService.get(identity, task_id)`先确认任务访问权；Identity由宿主注入。equipment_id必须在宿主可信对象grant内，不由模型补造。

新增冻结`InquiryPolicyConfig`由宿主加载：policy_version、tenant_id、factory_directory_version、factory_id→逐字别名集合、user_id→厂区/设备ID/能力授权。此为首个合成本地策略适配，不是生产IAM，不能从模型或服务返回创建。缺用户/对象/厂区/能力条目默认拒绝；不因为M2服务reader权限就推导对象授权。

厂区别名只查当前tenant的明确目录，禁止全局硬编码“一厂/1工厂”关系。重复别名指向不同factory_id返回ambiguous_factory，未知别名返回unknown_factory；无可信默认厂区不自动猜。首包不做模糊匹配或隐式Unicode归一化。设备ID未知/不在grant返回clarification_required或access_denied，不查询其他设备目录。

宿主通过M2 load_catalog(CatalogScope)取得当前policy_version一致、tenant/user/capability/factory授权交集。每项必需设备能力必须恰有一个enabled服务绑定；0个为missing_capability，多个为source_conflict。比较当前范围后冻结，不能按模型偏好、服务名称、最近注册时间选源。M2来源竞争拒绝继续保留，不因M3首包而放宽。

## 3. 冻结任务合同与T1复用

新增`InquiryTaskSnapshot`：task_id/run_id/correlation_id、任务revision、Identity、query_at（可信aware时钟固定）、policy/directory版本、equipment_id/factory_id、required_capabilities、M2 CatalogSnapshot、每entry的CatalogLease与参数grant。对象、能力、来源、时间全部在模型调用前确定。

模型只见本次相关工具alias、业务参数schema、用户问题和最小授权对象事实；不见target URL、argv、credential_ref/正文、管理令牌、原始服务描述。alias沿M2稳定命名，OriginalToolName保留逐字原名，仅在宿主SDK分发时使用。

T1改动限定：

- `ToolRegistry`和`ToolDefinition`原结构继续使用，动态definition的input_model为对应能力本地请求合同，output_model为独立`DynamicToolObservation`，不扩大旧ToolResult Literal。
- 同一个`ToolPolicy`新增`bind_task_grant(registry, identity, grant: TrustedInquiryGrant)->TaskCatalog`。grant只由已完成宿主访问/路由检查的snapshot构造；严格验证身份相等、目录/能力/参数grant对应，未知工具/重复alias拒绝。返回现有冻结TaskCatalog，仍由Executor逐次比较参数。旧snapshot(refs, question)不改。
- **仍使用现有ToolExecutor.execute**，不新增直接SDK调用分支到模型循环。它继续负责名称/参数/4096字节输入、授权、5秒期限、取消、64KiB结果与输出JSON重验；旧工具绑定校验不弱化。
- `DynamicToolObservation`是宿主独立StrictModel，字段tool=本地alias、object_id=None、queried_at=固定宿主query_at、outcome/reason、facts=None、source=None、evidence: ReceivedEvidence|None、complete、required_capability。这些外壳字段全部由本地handler生成，远端不能赋值。真正业务对象匹配在M1 bind_evidence完成后才可生成evidence；Executor当前tool/object_id/queried_at校验仍适用。
- 动态output_model按每definition固定alias/能力构建，禁止任意dict结果进入Executor。绑定错误必须data_error、evidence_valid=False；网络unknown/error可以作为观察，但不能成为已证实的“无故障/检验有效”结论。

TaskCatalog同一实例用于模型schemas与Executor。新增动态模型适配只提供`bind_catalog()->新视图`、`next(messages,run_id)`，gateway每run私有计数/attempt而共享真实ledger；首包scripted实现相同协议。绝不修改共享模型schemas。任何新增DeepSeek装配保持默认禁用，本包不触发真实调用。

## 4. SDK业务调用的唯一通道

新增内部`_ExecutorBoundCallAdapter`，由`build_dynamic_definitions(snapshot, host_context)`创建并只作为ToolDefinition.handler保存，不导出通用call_tool API/CLI。生产M2 RuntimeManager仍只有发现与关闭，不增加diagnose。模型/业务workflow只能拿到Registry/Policy/Executor，不拿ClientSession、transport或可调用闭包。

执行顺序：

1. Executor已完成本地输入/目录grant检查，再进入handler；handler核对参数与该definition对应的固定CapabilityRequest。
2. 当前M2 assert_current(lease)、宿主对象/策略版本及credential generation重检；失效立即拒绝，未知服务/撤权不连接。
3. 按M2同一TrustedTargets/credential resolver安全规则建立独占官方SDK会话（受信固定stdio argv或IP HTTPS，测试loopback例外隔离）；禁止sampling/roots/elicitation，日志固定脱敏。
4. 初始化并完整发现，按本地expected_schemas比较当前绑定工具与snapshot的schema摘要，变化返回stale_schema，不调用业务工具。未绑定扩展工具不可执行。
5. 在真正发送tools/call前再次检查lease/策略、预占本轮工具预算和调用id。仅使用已绑定OriginalToolName与固定业务参数，无远端/模型提供目标/身份。
6. 调用真实SDK，单次不超过5秒并受父任务剩余时限约束；不重试。只接受structuredContent，拒text推断JSON、isError假成功、非M1合同与>64KiB结果。HTTP解析前累计上限沿用M2 512KiB、禁压缩/redirect；业务合同最终64KiB。stdio官方reader限制继续明确保留。
7. DynamicEvidence JSON严格重验+bind_evidence绑定capability/version/factory/objects/query_at/coverage/category；检测tool schema、来源/完整性/时点，不把缺来源或partial提升为安全事实。
8. 完成SDK取消/退出/关闭后，再权威重检head generation/config_revision/discovery_id、policy/grants、credential generation。禁用/刷新/替换后的迟到结果拒绝。
9. 在短PG发布事务中按head当前代次取共享锁，检查后写本轮调用receipt（服务/alias/原名/版本/对象选择原因/耗时/固定错误/response hash），与disable更新形成明确先后。返回host构建的ReceivedEvidence及DynamicToolObservation给Executor再验。

第9步若首包需要独立调用审计表，新增下一空闲迁移号须父窗口确认；不改022或旧SQL。网络操作不持DB行锁。若存储不可用，不能发布有效证据；不得用“刚检查过”代替发布前事务检查。

仅在handler内构造会话，本地call能力不注册为管理功能。测试须证明直接向工作流提交原始tool名、恶意对象、伪身份、URL/管理动作都不会发出SDK tools/call。Python宿主代码本身在可信边界内；不声称对可任意改本地源码的OS操作者隔离。

## 5. 循环、预算、引用与输出

新增`external_inquiry`工作流，不重写旧check_facts_agent。三项设备能力为本轮必查集合，不要求执行目录中所有发现工具。首包scripted第一轮对三个alias提出固定授权请求，第二轮消费实际观察并输出结构化候选；不宣称自然语言自主选工具质量。

限额：最多3个模型决策轮、6次工具调用、父任务60秒、单handler5秒、参数4096字节、结果64KiB，模型上下文沿现有网关上限。initialize/list等为协议管理请求，只有实际tools/call计入六次工具预算；所有SDK请求仍受父deadline和发现页数限制。模型预算/ledger语义不另建一套。

首包每逻辑handler只调用一次业务tool，不自动翻页。若complete=False或next_cursor存在，原样返回partial及实际coverage，summary必须列未完成项，不能说无故障。后续分页须显式新授权cursor与预算，每次page各计tools/call，不在首包隐式加循环。

report使用新`dynamic-inquiry-evidence-v1`：task/run/correlation/revision、SYNTHETIC模式、snapshot/catalog/policy/directory版本、每调用alias+capability+服务与原名、executed/evidence_valid/complete、M1 ReceivedEvidence、model_steps/tool_calls/attempts/elapsed/stop_reason、required/observed/missing能力、候选摘要和citation call_ids。

候选引用只能指向本轮已通过绑定与发布二检的call_id。跨run/重复/未知/绑定错误调用不可引用。unknown/error是观察，必须区分；三项都已观察不代表设备可用。不可用来源、过期检验、故障分页未完、未关闭故障分别呈现；无批准/合规结论/设备控制。

## 6. 文件所有权（待D确认后实施）

新增：`tools/dynamic_mcp/routing.py`（可信目录/对象授权/单源决策）、`execution.py`（仅Executor-bound handler与typed观察）、`llm/dynamic_tool_model.py`、`workflows/external_inquiry.py`，相应test_dynamic_mcp_routing/execution/inquiry。如需发布receipt，新增迁移和registry方法由本窗口独占、编号由主窗口确认。

小幅修改：`tools/policy.py`增加可信grant绑定入口；其他T1 registry/executor仅在测试证明必要且D确认后修改，旧绑定/错误语义不可减弱；M2 runtime只抽取内部安全会话helper供两链共享，不扩大公开调用面。M1 contracts无需扩大ToolResult。禁止修改普通Bearer权限、旧工作流入口/SQL/总文档，不与其他包并发改T1核心。

## 7. TDD与验收

D通过后按以下顺序写实际RED→最小实现→GREEN，零付费：

1. routing：两个tenant同别名不串、未知/歧义别名零SDK、对象越权零SDK、缺能力/同范围竞争明确拒绝；single source含目录/路由版本稳定。
2. policy/Executor：同snapshot绑定模型与执行目录；模型伪身份/错对象/错时间/改schema/原名调用不执行；typed wrapper不接受伪host字段；旧T1全部回归。
3. SDK handler：真实stdio/HTTP设备asset+inspection+fault；错误对象/时点/capability/工具schema/来源/结果大小；timeout/cancel/disconnect分别保留；partial empty不成无故障；受信原名含点仍正确执行alias映射。
4. 真实PG并发：调用进行中disable/refresh/replace，取消通知使用实际wire id、结果不发布；发布锁与disable交错仅有明确先后；凭据/策略代次变化拒绝，存储失联fail closed。
5. scripted端到端：合成二厂明确设备，一条用户请求→可信路由→三工具动作→三份实际SDK证据→有合法引用的辅助候选；材料状态不变，报告可回溯到目录与来源；没有真实模型质量主张。
6. 运行新模块定向、T1/M1/M2/旧knowledge/business_bridge回归与Ruff；独立spec/code review所有critical/important关闭后，主窗口统一非live复验。

验收证据必须含实际tools/call wire、拒绝路径零call、共享TaskCatalog一致、工具预算/deadline、来源与引用、禁用迟到拒绝、真实协议与scripted性质分开。单纯连通、目录数量或发现成功不等于M3通过。

## 8. 失败、限制和回滚

任一必查缺证保留unknown/partial，不自动切备用源或重试。会话失败不改变注册head；业务证据不能自动批准/写设备。所有外部正文仅作为数据，不能改snapshot/权限/系统指令。

回滚先停止新inquiry入口并禁用本包服务，关闭会话，再撤新增workflow/adapter及Policy自有方法；保留旧T1链、M2注册审计和已撤权状态。无自动降generation/复活旧目录、无DROP旧表或整体reset。

首包只证明设备三能力的受控动态机制，人员/票据业务链、来源关系、自动分页、真实自然语言效果与企业生产接入仍分别待验。本文件仅设计；最终D审查通过才写源码/测试，不借M2已通过自动开放动态call。


## 9. 最终D补充与实施接口冻结

- dynamic ToolDefinition.clock固定snapshot.query_at逻辑时钟，与Executor前后绑定一致；HostReceipt.received_at采用实际UTC，父deadline用monotonic。实际执行晚于查询时点合法，远端queried_at错误必须拒绝。
- 全模型轮共享seen_call_ids，重复ID在Executor/SDK之前拒绝；attempts（包括非法参数等执行尝试）与wire_calls（真正tools/call）分别硬限6，第7次零wire；无隐式重发。
- 批准新增023_dynamic_mcp_calls.sql调用审计，不改022/旧SQL；只增加自有registry方法/表，独立initialize，不改主initializer。
- 共享接口：routing.py提供InquiryPolicyConfig/InquiryRequest/InquiryTaskSnapshot、async prepare_inquiry(service,identity,request,policy,registry,query_at)->snapshot；snapshot含identity、query_at、entries、requests(每alias对应CapabilityRequest规范JSON)、policy/catalog/directory/task/run版本。ToolPolicy.bind_task_grant(registry,identity,grant)接可信FrozenTaskGrant(identity,grants tuple[(alias,canonical参数JSON)])。
- execution.py提供ExecutionHost(registry,targets,credentials,audit,authorize)、CallBudget(max_attempts=6,max_wire_calls=6)、build_dynamic_definitions(snapshot,host,budget)->ToolRegistry。唯一SDK调用作为definition.handler内部能力，公开入口不返回callable/session。SQL023与registry新增业务resolve/publish审计方法由execution实现所有权覆盖。
- workflow external_inquiry.check_external_inquiry(service,identity,request,policy,registry,host,model,trace,limits=None)->report；先prepare再build definitions，再同一TaskCatalog绑定模型和Executor。新scripted模型可从bind_catalog得到固定grants，依次提议三能力并引用本轮观察。旧模型next协议保持。
