# P5阶段交接：工程Gate通过，接续P6质量闭环

2026-09-27。用户9/27在协调任务明确恢复此前暂停与长期自动推进授权。按路线图逐包实现、亲自验证、保留失败/退化、更新status/矩阵/学习/handoff后自动下一包；不等常规设计许可、练习或“继续”。仅明显范围变化、破坏性操作、真实业务副作用、关键输入缺失或预算不足问一次，独立工作继续。同目录唯一代码写入，不新建worktree。

## 当前实现和证据

WP01提交b035589：两类SYNTHETIC事件/SourceBinding、SQL005原始记录/水位/一次关联。原始报警先独立提交，关联锁/Saver/结果写共用连接。WP02提交0dcb302：显式材料revise及恢复（SQL006）、有限感知候选/反馈/当前性（SQL007），保留取消与部分观察。未修改原始报警、未自动批准或生成实时控制指令。

WP03本次提交见Git最新：FastAPI0.141.1/Uvicorn0.53.0，宿主token→Identity与来源/事实引用，32KiB请求边界；start request_id幂等，原resume仍只补充waiting_input；review持久cancel_requested（SQL008），进程退出后recover不重发；SSE最新持久快照/摘要ID、断连与业务取消分开。[当前模块入口](module-map.md)、[服务演示](service-demo.md)、ADR011—013。

[最终工程Gate](evidence/wp03/gate-report.md)：最终CI400 passed、0 skipped，84真实PG标记；实际HTTP/SSE/持久取消/进程重启通过；干净venv从wheel离源码运行两类完整链，85安装源码/资源指纹与当前CI一致；9资源/9CLI、P5两链、原P4 9/6/3/2及61故障通过，唯一账本32→32。400测试基于保留用户译文的当前工作树，提交不包含这些译文。

初CI395项9失败保留，至少4项是子进程ImportError build_graph。当前源码/pyc/新进程正常，历史触发原因未证实，未更改超时/断言来通过；恢复后16相关项、399及最终400全绿。clean-service-v1有PermissionError却报passed的验收漏洞已红绿修复并明确排除；v2缺包指纹也不能用于最终Gate，v3才绑定当前85项。独立只读审查还发现新增源码/旧wheel混用缺口，已补全集核对。旧失败/哈希不重写。

## P6首要质量阻塞：Q-P5-001

**真实感知模型验收仍未通过：0/2。** 既定deepseek-flash两次invalid_output、5072token，字段根因因旧网关缺诊断无法回溯；后补type/loc诊断只经替身验证，没有追加请求。后续scripted重核/合成反馈/服务API通过不能当真实模型成功或用户本人确认。[原始结果](evidence/wp02/live-v1.json)/[质量项](../../quality-items.md)。

按[P6计划](../phase-06-quality-reliability/plan.md)/[验收](../phase-06-quality-reliability/acceptance.md)先核对Prompt/Schema/解析与诊断，提出具体可证伪假设，离线验证后最多两次初始增量真实验证。延续同一感知问题，继续用可信P5-WP02归属，已消耗2/10，不因进入P6改包重置；若后来确有独立实验包需明确合理归属和测试，不能借换包绕限。失败照计，不盲重试/降边界。最终若仍不能证明有效，必须列“未通过”及所需用户决定，不能宣称完整感知Agent可用。当前不需重复问预算。

唯一PG授权20260920-long-term-v1累计32/100：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9、P5-WP02=2（failed），其余30 succeeded，无reserved。已知新授权输入59475/输出8341/总67816token，P1历史3次1184另列，金额未查。调用前读即时账本；网关请求前预占，失败/未知不能退款或还原旧数据库重置。P5-WP03零模型请求，未读docs/DS.txt。

## 环境与保护

PG17.11在127.0.0.1:55432，系统PG10不动。9/27恢复时项目PG未运行，已仅启动项目实例；新shell scripts/dev-postgres.ps1 -Action Env。本任务已停止其临时HTTP/Java进程，PG留供接续。Jaeger单独Env；BGE缓存.runtime/embeddings。新事件/事实/知识用独立2026-09-22T04:00Z；旧P2/P3/P4保持原2026-09-20T12:00Z等冻结时点。

已建干净venv .runtime/p5-service-clean/venv，依赖按锁安装，无需重复安装；当前项目wheel在.runtime/p5-wp03-final-dist。config-v3.json含本地随机token且已忽略，不输出/提交；它所指任务/反馈已用于回放，复跑用prepare_service_demo生成新配置。源文件仅换行符变化也会影响严格字节指纹，不能改旧报告哈希掩盖。

本机Docker/Compose不可用，WSL状态失败；Compose/Dockerfile为未执行模板，远程GitHubCI没有推送/运行。本地CI和原生清洁启动确已实测，不能把未验证部署计通过。材料任务的通用取消、生产OAuth/设备接入未做，不等同于已完成的review取消。

用户16路径32行中文译文和.idea仍unstaged，映射docs/refactoring/user-change-map.json、备份.runtime/refactor-backup。用户9/26重排docs/learning-log.md为P1→P5及25目录锚点、19历史记录；原样保留并新增WP03条目/目录，整体仍unstaged，不整文件提交或改回倒序。独立wp03-learning.md已提交学习内容。恢复备份.runtime/p5-resume-20260927，可核对移除新增条目后与用户版逐字节一致。

下一任务冷启动读AGENTS（本轮未发现）、product/status/roadmap、本handoff、quality-items、P6 plan/acceptance与必要ADR；核对Git/预算/最小smoke后直接WP01诊断。P2/P3/P4模型引用不足/无增益、历史PG异常退出/P3长暂停超时等未知原因继续保留；个人掌握独立待验，每包3—5题与可选实践不阻塞。协调任务01a0b000-4960-7571-b6ea-e952a22bbd16只读，有既有30分钟自动续接id=2-0，不重复创建自动化或并行写码。
