# ADR011：原始事件与一次关联结果分离

2026-09-22，P5-WP01。沿用责任包和ADR002，首包无模型请求。

两类事件只有SYNTHETIC未戴安全帽、可燃气体异常；报警active来自模拟生产者声明，不执行阈值判断或任何控制。原始JSON经严格合同校验后保留原值；格式/类型非法在接收边界拒绝。没有摄像机/设备接入，不声称视觉识别准确性。

身份与source_id来自可信宿主；SourceBinding显式声明唯一task/object/material revision/run及时窗。该绑定是合成配置，不是从材料自然语言证明空间或设备归属。跨身份配置在SQL前拒绝，未知来源与错误对象/类型保留原事件及拒绝原因。正文无身份/任务/授权字段。

SQL005独立保存原事件和来源水位。接收事务以tenant/user/source串行，事件ID同内容幂等、不同内容拒绝。序号严格递增且observed_at不倒退才推进水位；重复序号、过期、未来事件均不推进。流序号没有跨source的全局顺序。收到事件先提交；进程退出、任务锁忙、无Agent时仍可查原始报警。

关联结果采用一次写入：授权事件后，使用现有材料Registry锁与checkpoint读，检查当前revision/run、材料无未完成operation以及合同。最终提交再次核对来源水位、事件/绑定有效期。任务锁、checkpoint读与关联结果写共用同一连接；连接被终止时无法通过另一个连接发布迟到结果。接收事务与关联事务有意分离，不声称两者原子。

已有linked仅证明processed_at对应的关联快照，不代表之后材料/来源永不变化。WP02必须重新核对当前性后才采证/反馈；原始报警永远保持active。未知任务与不可访问任务统一task_unavailable。该包不自动resume、不重开已结束Graph，也不关闭/压制/降级报警。

本地CLI `python -m anlan.interfaces.events_cli`提供init/receive/process/show；--tenant/--user/--binding都是明确的模拟宿主配置，不是生产鉴权。--as-of为合成回放时钟。示例使用独立2026-09-22时段，P2/P3/P4冻结输入不改。

证据见[P5-WP01](../phases/phase-05-events-service/evidence/wp01/)，包含两个独立进程类型的12命令回放、真实PG故障、红测以及当前关联连接被pg_terminate_backend终止后仍不能写结果的测试。数据库实例本身未重启，验证的是客户端进程/连接恢复。
