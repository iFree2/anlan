# ADR012：显式材料修订与有界感知重核

2026-09-22，P5-WP02。

已结束材料任务的修订采用同task/thread的新revision/run，新增显式revise入口，仅接受awaiting_review、无interrupt/next/pending operation以及正确expected_revision。resume仍只处理waiting_input；两种operation共享request_id命名空间并核对kind，不能用跨方法重放绕过合同。SQL006只扩展kind约束，旧SQL001字节及material-state-v1字段不改。Graph从显式新输入走START→analyze，恢复认出已写run，不重复合并/增版；补成缺字段自然进入原interrupt循环。

原始事件不触发材料字段自动修改。宿主绑定当前材料后接收新事件，独立感知重核使用receipt/request唯一键、PG保存review/run和一次结果。会话advisory锁覆盖重核生命周期，崩溃释放；recover只有拿到此锁才可标interrupted，绝不重发模型。无法判断的已预占请求仍在唯一预算账本计费次数内，恢复只读对应run尝试。

感知角色复用P4三次只读采集，输入固定事件＋当前材料＋已采证据（最多24000字节），一次20秒模型step，网关固定P5-WP02。候选仅能表达有限关注类别、引用编号与人工核对步骤枚举，无自由控制命令或批准/报警字段。未知必须完整，事件类别引用e1，知识关注只引用实际ok的o3；这仍不证明真实事件或模型语义质量。

入库前重新核对材料/事件水位/时效，迟到结果留存为stale；get动态报告currentness，反馈同时持有task锁、来源事务锁与review行锁并校验revision，避免把旧版本候选确认成当前。反馈只记录confirmed_event/disputed_event/needs_verification，不写原报警、材料或权限；合成回放反馈不等于用户实践。

取消是跨采集、模型与最终落库的信号。父取消先要求受控collector汇合已完成观察，再传播CancelledError；可选progress在最终材料复验前保留经过结果合同/来源冲突处理的观察，即使材料变化使收尾失败也不覆盖取消。模型子任务清理后再次采样信号，PG选择终态前再检查，避免迟到候选变completed。合作式取消不能强杀任意阻塞扩展，数据库故障也可能留下pending，此时显式recover而不是暗中重发。

模型适配器按run_id保存attempt归属、串行保护同实例调用，未发送/取消排队者不能继承上次attempt。真实2请求均invalid_output，0/2接受；随后补type/loc字段诊断，只经替身验证，根因仍不明且无重试。[真实证据](../phases/phase-05-events-service/evidence/wp02/live-report.md)。这是工程故障保留能力，不是模型质量通过。
