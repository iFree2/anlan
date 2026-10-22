# 安澜双角色材料核查协作设计（P12）

## 用户确认与交付范围

2026-10-22 用户确认：申请人与安全管理人员独立身份、各自独立会话，共享同一份作业申请；先梳理方案，确认后分批在各自会话实施，最后重新部署和录制双角色协作视频。用户进一步明确：本期截止到**材料核查完成**，不做正式审批和开工授权。

采用单应用双角色，不拆两套后端、不新增自主审批 Agent。保留现有“受控路由器 + 既有材料工作流”，扩展共享业务权限与人工协作状态机。相比独立门户，单应用便于维持单一业务事实；相比只切换前端角色，服务端授权能覆盖直接 HTTP 请求。

## 已有实现与差距

- `common/models.py:Identity` 仅有 tenant_id/user_id；`interfaces/service_config.py` 以私密 bearer token 映射可信身份，尚无业务角色。
- `infrastructure/conversations.py` 会话按 tenant/user 隔离；继续保持，不让管理人员读取申请人私人会话。
- `infrastructure/postgres.py`、`infrastructure/events.py`、`infrastructure/perception.py` 的任务、事件、核查均按单用户归属；不能只在页面增加两个窗口。
- 材料 `waiting_input/awaiting_review` 是分析状态，不是申请的提交/退回/人工核查状态。
- 线上 P11 已部署；既有记录和预算不可覆盖、重置或悄悄共享。P9/P10不在本期范围，SQL012保持预留，不开展动态MCP。

## 角色、身份与授权

服务端 token grant 增加可选 `collaboration_role: applicant | safety_manager`。缺省为未加入协作的 legacy 身份，不能自动获得任一新角色；同tenant/user的多个token不能声明矛盾角色。Identity不扩充可由客户端填写的role。角色、tenant、操作者均只由认证配置确定，HTTP载荷带额外身份字段拒绝。

第一版使用两份独立的私密演示连接配置，标注演示身份，不声称企业SSO已完成。一个人对应一种协作角色，申请人与核查人不得是同一user。由申请人在首次提交时，从同租户服务端配置的安全人员名单选择一人；不做抢单、转派、会签和任意同租户查看。

| 动作 | 申请人 | 被指定的安全人员 | 其他身份 |
|---|---|---|---|
| 私人会话 | 仅自己的 | 仅自己的 | 仅自己的 |
| 创建、编辑材料 | 自己申请的可编辑阶段 | 禁止 | 禁止 |
| 提交、重新提交 | 自己申请，显式确认 | 禁止 | 禁止 |
| 共享材料与业务时间线 | 自己申请 | 被指定且已提交的申请 | 禁止 |
| 提补充要求、完成人工核查 | 禁止 | 本人待核查申请，显式确认 | 禁止 |
| 事件核查、人工事件反馈 | 只读允许公开给申请人的业务结果 | 本人已分配申请，可发起核查并记录反馈 | 禁止 |
| 模拟事件 | 不开放申请人入口 | 演示模式且本人申请范围内 | 禁止 |

任务业务归属和执行者分开：原owner可作为内部资源索引，但授权与审计永远保留真实actor。不得将安全人员替换成申请人Identity调用整条流程。若底层存储需owner定位资源，参数须明确为storage_scope，经授权后解析，不能由HTTP传入。角色检查、参与关系、租户和状态检查必须在后端执行，不能依赖LLM或隐藏按钮。

## 唯一申请与状态机

申请沿用材料task_id，不复制第二份材料，不创建第二个工作流checkpoint。增加协作元数据：tenant、applicant_user_id、reviewer_user_id、status、version、submitted_material_revision、completed_material_revision及时间。材料字段与最新revision仍以既有工作流为准，不在协作表另存一份“当前材料”。

| 状态 | 业务含义 | 允许的下一步 |
|---|---|---|
| draft | 申请人准备材料，未交给安全人员 | 编辑、确认submit |
| under_review | 已提交某一材料版本，等待指定安全人员核查 | request_changes、complete_review |
| changes_requested | 安全人员已发出具体补充要求 | 申请人编辑材料、确认resubmit |
| review_completed | 本轮材料核查完成，不是批准作业 | 本期只读；进一步流程线下处理 |

创建动火材料任务仍需原二次确认；加入协作后初始为draft。模型材料分析结束不自动submit。submit要求材料分析已到awaiting_review、四项材料不缺失、无pending执行、无失败分析；offline/scripted演示允许但必须清晰标注，不能混称真实模型质量验证。首次submit绑定核查人及材料revision。

request_changes至少包含一条具体要求，保留原提交材料版本，转changes_requested。补材料仍走现有工作流，材料revision递增；resubmit要求有新材料revision且分析完成，保持同一核查人，保存本轮补充说明。under_review阶段冻结申请人的材料写入，防止核查中静默变化。

complete_review要求：真实安全人员身份、本人分配任务、under_review、无pending材料操作、当前材料revision等于submitted_material_revision、非空人工核查说明，并经确认卡片再次确认。写入completed_material_revision和review_completed，页面明确“材料核查完成，不代表作业批准”。不产生approved、permit_issued、开工或关闭报警指令。

review_completed本期不允许直接改材料或自动重开；如后续需要修订，另做明确重开设计，不在本期隐式实现。历轮人工意见与模型事件核查仍保留；材料更新时旧版本结论标为历史/过时，不覆盖旧记录。事件核查的currentness不等同人工材料核查完成。

## 独立会话与共享信息

两人可用同一URL在不同浏览器上下文打开，分别选择独立访问配置。各自左侧仅显示自己的会话；管理端有“分配给我的待办”，申请端有“我的申请”。选中共享申请时绑定到本人会话，服务端再次校验参与关系，不接受任意task_id绕过授权。

共享内容限材料、人工补充要求、申请人本轮补充说明、人工核查结论、允许公开的事件结果与业务进展。普通聊天、提示词、推理痕迹、错误详情、私有偏好、令牌和对方会话ID不共享，也不送入对方的模型上下文。

新增协作命令候选：submit_application、request_changes、resubmit_application、complete_material_review；对应待确认记录必须冻结task_id、动作、目标材料revision、协作version、核查人/问题/说明等完整载荷。普通“确认”只能执行本人会话当前保存的那一张卡片；状态/版本过期要求刷新并重新确认，不能由模型重新解释成另一动作。管理人员不能误走申请人材料写入路由。

查看待办、查看进度、选择任务、读取共享时间线不修改业务状态；可使用结构化控件，不要求额外模型请求。闲聊不改材料。暂停/恢复仅控制本人会话引导，不改变共享申请状态。

## 持久化、通知与并发

使用SQL017增加collaboration_applications、collaboration_commands、collaboration_events、collaboration_notifications；所有新表显式anlan_v2 schema。协作应用与原task_id关联；不修改旧owner或现有checkpoint。实现文件分contracts/policy/store/service/access adapter，避免将全部业务塞进原ConversationService或api.py。

每个协作写命令包含request_id、expected_application_version和expected_material_revision。幂等范围包括tenant/actor/request_id；重放时验证task/action/完整载荷一致，同载荷回放原结果，改载荷409。协作version、业务事件、收件通知和命令结果在同一PG事务中提交；失败不产生半条“已通知”。

跨Graph与协作元数据使用同一task级互斥协议；核对真实checkpoint/pending operation后才允许协作提交/完成，不能依赖前端缓存或协作表的过期副本。保持既有任务锁和恢复边界，不在长模型调用外另开会失效的独立锁。业务事件记录actor、角色、task、材料revision、协作version、动作和时间。

持久化收件箱通过认证的快照流/有界轮询在本人会话显示“业务消息”，不复制对方私聊。事件ID去重，未在线用户重连可补读；SSE cursor不可访问别人的通知。共享进度的变化不应让另一用户被迫读取他人conversation。页面刷新和进程重启后双方会话、任务关联、待办、补充要求和核查结果都能恢复。

## HTTP与兼容约束

新增 `/collaboration/applications`（列表）、`/collaboration/applications/{task_id}`（受限投影）、`/collaboration/applications/{task_id}/commands/{action}`、`/collaboration/notifications`及认证更新入口。接口命名如需调整，在批次交接同步文档与调用方，不留下双重合同。

原 `/tasks`、resume/revise/recover、history、console事件/核查、通用事件/反馈入口、conversation切换/恢复均需检查共享任务权限和状态。不能出现新入口禁止编辑、旧接口仍能直接写的情况。未纳入协作的legacy任务保持原私有归属；安全人员不能遍历旧任务。新角色使用旧入口也不得绕过约束。

迁移增量且可重复运行；不批量把旧申请分享给新角色、不重标预算。发布前备份与记录旧行摘要。回滚若存在新协作记录，必须停用或限制旧业务写入口，旧版owner-only写权限不能绕过under_review冻结；允许只读回滚或前向修复，不把数据库恢复到旧快照抹掉新记录。

## 验证与交付

每批TDD、真实隔离PG测试、Ruff和独立交接。最终用两个独立浏览器上下文完成“申请→提交→安全人员提补充→申请人补充/重提→安全人员核查完成→双方恢复读取”，同时验证同租户未分配安全人员、另一申请人、跨租户身份及旧API越权。UI只验按钮隐藏不算授权通过。

不改TLS/SSO/SLA边界，不接真实设备，不新增正式审批和开工授权。非live开发不触云端；真实请求只在最后发布批次做有界联调，沿用累计100、对话P11-WP01上限30、材料/事件P11-WP02上限10，先读账本再算本次额度，失败也计数，不自动重试。若额度不足或需要新包，单独请求授权，不能默认扩额。

视频保留慢速柔和合成女声与口语化业务说明，明确标注两种身份、展示同一个申请编号和往返消息；继续说明合成数据、核查完成不等于批准作业。不得以同账号切换文案冒充两个角色。

## 批次与确认

用户已批准上述业务方向与结束边界，并要求文档后直接分批实施。当前协调会话维护总进度；每批新建独立Codex会话，同一本地检出串行执行，验收并提交后才启动下一批。无新的实质范围变更不重复要求用户确认。详细批次见配套实施计划与P12验收清单。
