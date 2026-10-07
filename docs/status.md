# 当前状态（唯一入口）

- 项目：安澜2.0。P1—P7原计划有限工程Gate已交接；用户于2026-10-07追加的P8轻量操作台及阿里云学习部署已完成运行验收。工程完成不等于模型泛化、生产能力或本人掌握。
- 当前工作包：P8-WP01页面＋WP02云端部署已收束。[最终交接](phases/phase-08-console/handoff.md)、[验收](phases/phase-08-console/acceptance.md)、[部署/运维](phases/phase-08-console/deployment.md)。提交以Git最新日志为准。
- 入口：http://47.93.218.52/anlan/console。浏览器选择本机ignored .runtime/aliyun-console-access.json；仅演示访问token，不含SSH/PG管理凭据。云端新库anlan2_console，systemd非root用户anlan2，原PG13/现有库与网站保留。原网站200且摘要不变。
- 当前能力：材料表单/缺项追问/补充/修订、任务列表、两类服务端合成事件、事实/示例依据查询、核查候选/未知/引用、人工反馈、过时结果拒绝及PG恢复。材料offline、核查scripted_double；没有页面live模型入口或云端模型密钥。
- 最近验证：本地CI-v3记录463 passed/0 skipped，交接时受检源码指纹一致；7个console包文件与当前wheel源码一致、SQL009在包中；公网浏览器九项通过，三项事实/知识查询均ok；服务PID变更后任务/事件/反馈/核查快照完全一致。[本地验证与失败](phases/phase-08-console/evidence/verification.md)、[公网浏览器](phases/phase-08-console/evidence/cloud-browser-v1/report.json)、[重启核对](phases/phase-08-console/evidence/restart-result.json)。
- 最终只读交接：[复核报告](phases/phase-08-console/evidence/final-readonly-verification.json)。页面/健康200、认证就绪200，原网站摘要及已有任务/事件/反馈快照一致；未执行SSH、重启或模型调用。公开预算报告缺少云端逐条字段摘要比对，此项未独立复验；不要重复运行bootstrap作为同步或修复。
- 保留的本轮失败：缺Playwright自带浏览器、移动端引用溢出、一次环境中断导致未完成CI、软件源超时、pgvector缺RPM构建spec、localhost ident认证拒绝、重启后首次读取未成功。后续复验不追认未知中断根因，也不声称无停机。
- 模型预算：20260920-long-term-v1，46/100，44成功/2历史失败/0pending；100累计/每包10上限不变，失败与预占计数。P1历史3次1184token另列；新授权已知总81753token，实际金额未查。本包真实请求0。
- 唯一预算写入位置已切换到云端PG；46原始尝试/时间/用量保留。本地PG相同生产authorization触发器冻结为历史只读，其他测试授权不受影响；本地offline演示可继续。真实调用不可用旧本地账本预占或重置额度；切换回本地前必须做单一写入方交接。[ADR014](decisions/014-console-cloud-deployment.md)、[冻结验证](phases/phase-08-console/evidence/budget-cutover.json)。
- 历史实验归属：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9、P5-WP02=4、P6-WP03=8、P7-WP03=4。原感知失败0/2及后续最低2/2不改写，未知旧字段根因保留。后续模型请求先预占云端账本，不换包绕限、不隐式重试。
- 仍开放：[quality-items](quality-items.md)的Q-P6-001 Judge误判、Q-P6-002同任务并发409。Memory/多职责无已证实质量收益、引用缺口与历史未知故障保留；Mem0仅静态比较。当前HTTP/IP/模拟身份，TLS、生产规模/SLA、真实设备/人员、Docker/Compose与远程GitHubCI未验证。
- 用户改动：16路径32行译文与.idea保留；learning-log原P1→P5重排与P6/P7/P8条目保持，整文件不提交。P8核对16路径无意外变化，见[evidence/user-preservation.json](phases/phase-08-console/evidence/user-preservation.json)。旧项目始终只读。
- 本人掌握：[能力矩阵](capability-matrix.md)与[学习记录](learning-log.md)独立待验证；仅本人历史追问修改/演示有证据，AI编写/运行不升级本人。下一步先按[P8五题与小练习](phases/phase-08-console/wp01-learning.md)亲自操作一次材料→事件→反馈。
- 协作授权：9月28日暂停已由10月5日“继续推进”解除；常规既定范围可自动推进，范围改变/破坏/真实业务副作用/必要输入或额度耗尽才暂停依赖部分。原自动化2-0已在10月5日工程收束后删除，本轮不创建定时任务或无目标新阶段。

后续冷启动：适用AGENTS → 本状态 → P8交接/验收 → ADR014 → Git/index与必要最小smoke。云端服务保持运行；本机PG17在55432只供offline学习/测试，系统PG10未动，新shell先scripts/dev-postgres.ps1 -Action Env。SSH/PG管理凭据仅连接时使用，不读取或公开私密配置。未有新的具体目标或本人证据时，不重复既有包、付费实验或凭长期授权无限扩栈。
