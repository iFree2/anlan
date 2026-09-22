# P5进行中：WP01通过，继续WP02

2026-09-22。继续同目录唯一写入，沿用长期授权逐包实现/亲自验证/保留失败/更新状态后自动下一包；不等常规许可或练习。尚未完成P5，不能创建P6或宣称服务/感知Agent已完成。

WP01已实现严格两类SYNTHETIC事件、宿主SourceBinding、SQL005不可变原始记录/水位/一次关联结果、独立CLI。身份来源不在正文，关联同task/revision/run、对象与时窗；真实PG并发去重、乱序/重复序号/过期/未来/未知来源/错对象/跨身份/不存在任务/材料pending与合同/版本不匹配均有证据。关联锁、Saver读与结果写共用现有专用连接；pg_terminate_backend终止此连接不能写迟到结果，原始报警仍active且可恢复。

验证：341全量（54真实PG、零skip）＋1新报告验真；42事件测试；2类型12跨进程命令回放；P4原冻结9/6/3/2及61故障通过；wheel离源码全部模块/6资源/7CLI，ruff/lock通过。详见[WP01验证](evidence/wp01/verification.md)、[ADR011](../../decisions/011-synthetic-event-association.md)、[逐步演示](event-demo.md)。原始事件已持久化与客户端重启经过测试，数据库实例没有重启。

新请求0，未读模型凭据。唯一PG授权20260920-long-term-v1仍30/100，P3-WP03与P4-WP02各9、P2两包各6。P5真实实验必须先固定新包号并测预占归属，再读即时账本；不占旧包余1次、不重置。已有模型语义不足/无增益与PG历史未知原因继续保留。

下一包按[WP02计划](wp02-plan.md)：先显式材料revise状态机及恢复，不能用resume重开awaiting_review；再感知有界模型合同、既有事实/知识采集、持久化重核/反馈和当前性。候选反馈不关闭/压制/降级原报警、不自动批准或输出实时控制命令。首次最多两类型各一次新包真实实验，前置测试/账本检查，不为了漂亮结果追加。

环境PG17.11:55432正常；每个新shell scripts/dev-postgres.ps1 -Action Env。Docker未找到，wsl.exe存在但组件未安装；后续做实际原生清洁启动/CI，Compose不可用单列，不能把配置当部署通过。Jaeger需独立Env，旧area-001按原冻结2026-09-20T12:00Z回放；新事件fixture独立2026-09-22T04:00Z，不改旧日期。

原16路径32行用户译文及.idea均保留unstaged。新包基本只增加文件，verify_package_layout.py按新增资源/CLI更新，旧资源不改。功能涉及带译文的service/postgres时必须只stage自己改动；映射/备份仍在docs/refactoring/user-change-map.json与.runtime/refactor-backup。协调任务01a0b000-4960-7571-b6ea-e952a22bbd16只读跟进，已有30分钟自动化id=2-0，勿重复创建。
