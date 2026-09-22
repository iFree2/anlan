# P5-WP02：条件变更与感知辅助重核

2026-09-22。沿用持续授权，在WP01验证和提交后直接实施；不等待常规确认。个人掌握仍独立待验。

**目标**：为两类合成事件采集既有当前事实/知识，给出有界、待人工确认的感知候选，持久保存失败/反馈；材料变更和较新事件使旧候选显式stale。

## 版本设计

材料保持原task/thread和material-state-v1字段。新增显式`revise(expected_revision, fields, request_id)`，仅允许awaiting_review且无interrupt/next/pending operation；resume仍只用于waiting_input。revision+1和新run持久保存在`kind=revise`的operation里；重用既有Graph START→analyze，不通过Command(resume)伪造补充。恢复识别已经保存的新run，不重复合并/增版。SQL006只扩展operation kind检查，旧SQL001字节不改；旧程序遇到新kind无法恢复而显式拒绝。

事件不会自动修改材料。新的来源事件触发独立重核，绑定仍要与当前材料revision/run一致。人工修改材料通过显式revise/resume完成，宿主重新登记当前绑定后才能接收新事件。原事件/已完成关联结果不改。

感知重核使用独立review_id/run/request_id和状态pending→completed/failed/cancelled/interrupted。同request重复返回同记录，禁止隐式模型重发；进程中断后recover只标interrupted，新的明确请求才可能调用模型。所有候选是一次时点证据，get/feedback都核对材料、事件水位和有效期；stale保留旧内容并阻止确认。

## 职责与边界

- `workflows/service.py`扩展显式材料revise；`infrastructure/postgres.py`装载SQL006。复用同连接锁/Registry/Saver。
- `workflows/perception_contracts.py`：模型仅能返回事件ID、有限关注类别、引用ID与有限人工核对步骤枚举；不允许自由控制指令、报警操作或批准字段。结构校验不证明模型语义。
- `workflows/perception.py`：复用P4 collect_parallel的3只读工具与deadline，冻结事件/材料/身份/as-of；对象须与可信FactReferences.area_id一致。受控感知角色一次模型step；输入字节/输出/时限受限，取消与失败保留原始报警和已采集证据。
- `llm/perception.py`：替身与真实模式明确区分，真实网关固定P5-WP02包号（不得占P3/P4）。在网关/账本归属测试和读取即时生产账本后，最多两类各一次既定deepseek-flash合成实验；失败无重试，不为好看结果重复调用。
- `infrastructure/perception.py`与SQL007：持久化重核与人工反馈。反馈只记录confirmed_event/disputed_event/needs_verification，expected_revision控制并发，request_id幂等；反馈不修改原始报警、材料或权限。
- `interfaces/perception_runtime.py`、CLI负责装配/恢复与权限；不建立第二Graph、事实库、Memory或预算。

## 顺序验收

- [x] 先写材料已结束修订的红测：结束→revise→新revision、重复/旧版本/等待输入拒绝、崩溃后恢复不二次合并；实现后跑原材料/PG恢复。
- [x] 先写两类候选合同/引用/对象与越权/当前性/取消/预算测试，再实现受控采集与模型适配。
- [x] 先写真实PG重核/反馈并发幂等/中断恢复/较新事件与材料修订stale测试，再实现持久化装配。
- [x] 两类事件→证据→反馈完整跨进程回放；必要真实模型实验先测试可信P5包号并查共享账本，保留所有尝试/不足。
- [x] 全量/旧Gate与wheel必要回归，文档/矩阵/学习/handoff/失败归档，提交后自动进入服务/SSE/清洁启动WP03。

执行沿用TDD与verification-before-completion；具体测试模块与实现一一对应，失败输出写独立新文件。持续授权已明确同目录，不新建worktree，不整文件stage用户译文。
