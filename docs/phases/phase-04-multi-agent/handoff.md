# P4阶段交接：工程Gate通过，启动P5

2026-09-22。[最终Gate](evidence/wp03/gate-report.md)。用户长期授权按路线图逐包实现、亲自验证、保留失败/退化并更新状态/矩阵/学习/handoff，直接自动下一包；不等常规范围确认、练习答案或“继续”。仅明显范围变化、破坏性操作、真实副作用、关键输入缺失或额度耗尽暂停依赖部分问一次，独立工作继续。

## 已实现与包结构

WP01两个确定性只读职责分支、固定fan-out/fan-in，可信身份/材料revision/run/as-of、父子ID、预分配3工具预算、deadline、取消/部分失败/来源冲突，保留成功证据。没有模型的采集分支不能称多模型自治。

WP02risk沿用P3 ReviewCandidate，evidence只看已入上下文观察/知识和候选逐claim复核；固定协调只标支持/异议/不可用，永不批准/自动改候选。父最多2模型step/45秒，子ID=parent:risk/evidence，共享PG预占。DeepSeekReviewModel默认P3-WP03，可信P4入口为P4-WP02；报告与网关包号必须一致。

WP03 Java两只读HTTP门面→Python既有FactTools，MCP官方SDK1.30.0维护v1 stdio、JDK21。核心服务验证token绑定身份与宿主预期identity/as-of，无身份工具参数；大小/时限/权限/未知完整。SDK取消需显式CancelledNotification，408映射timeout，旧MCP入口真实验过。只读底层I/O可能晚结束，但不发布迟到结果。不是生产OAuth或第二事实权威。

用户中途要求R1职责分包，已独立提交d7b56d8并向协调任务回传。`interfaces/workflows/llm/knowledge/memory/context/tools/infrastructure/common`；db连接配置不装配workflow，interfaces/runtime仍同connection交给Registry/Saver；Memory偏好、KnowledgeCitation、AnalysisFailure为轻量合同。根只保留5旧CLI薄转发。详见[R1交接](../../refactoring/handoff.md)、[映射](../../refactoring/module-map.json)、ADR009/010。内部新代码使用规范路径。

## 实际验证与失败

297全量（34真实PG、0跳过）＋2新Gate验真测试；P4冻结9/6/3/2与61故障、P3冻结8/9/24、P2冻结11/11、wheel离源码/5资源/CLI均通过，ruff/uv锁通过。Java/MCP跨语言使用既有PG任务，材料不变。新增Gate没有真实模型请求。

失败都保留：WP01取消清理吞父取消、Memory截止/时点不一致、最后材料检查未记取消；WP02 HTTP普通异常丢候选与预占报告、报告包号错、trace完成事件误记error；WP03身份错配、SDK单次取消未通知/408误分类、流包装缺async context；R1新测试导入被批量误写后修复。用户chat占exe导致uv add同步失败，后用no-sync依赖安装且未杀进程。原PG异常退出与P3长暂停超时根因仍未证明，不抹去旧记录。

## 模型证据与预算

本阶段只做WP02三任务单/双角色9请求/22461token，HTTP/Schema均成功；单模型应用接受2/3，双角色risk接受3/3，但证据审核1全支持、2异议。双角色多95%token/约74%模型阶段延迟；WP01两例并行更慢。不是泛化或因果质量增益；原始候选、AI逐条复核、材料引用缺口、位置映射漏检和离题引用见[真实报告](evidence/wp02/live-report.md)。AI复核不是本人实践/独立金标，个人掌握仍待验。

唯一生产PG授权20260920-long-term-v1，累计30/100：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9；无reserved未知。已知新授权输入54580/输出8164/总62744token；P1历史3次1184另列，金额未查。每包10/累计100为已告知保守次数上限，不是金额授权；失败/未知也占，禁止重置/退款/先发再改归属。P5首包零请求，后包真实实验前先接可信新包号并测试，再读即时账本；不能直接复用P3/P4剩余1次。

## 冷启动与接续

同目录D:/src/agent学习/安澜2.0，不新建worktree。先读适用AGENTS（此前未发现）、product/status/roadmap、本handoff、R1、P5 plan/acceptance及ADR002—010；Git/最小smoke后直接实现P5-WP01两类模拟事件最小合同/PG/关联/去重，不停在常规许可。原Graph恢复、SQL/assets、事实/知识/Memory、预算不重建。

用户原14文件32行中文注释/docstring现16路径，均保持unstaged；逐行对应`docs/refactoring/user-change-map.json`，完整备份`.runtime/refactor-backup`，.idea未提交。不要整文件stage这些译文。此阶段任务交接后不再改码；协调任务01a0b000-4960-7571-b6ea-e952a22bbd16只读，有既有30分钟续接id=2-0，不创建重复自动化。

PG17.11在127.0.0.1:55432，系统PG10未改。新shell运行scripts/dev-postgres.ps1 -Action Env；Jaeger2.21在16686，PowerShell7单独Action Env（Start已有实例会提前返回）。BGE缓存.runtime/embeddings。记录area-001已过期为预期，冻结回放明确2026-09-20T12:00Z，不改历史日期。用户uv run anlan chat可能仍占anlan.exe，不终止；用.venv/Scripts/python.exe或uv run --no-sync；旧console已验证正常。

复现P4：`.venv/Scripts/python.exe -O evals/phase04_gate.py --output <新路径>`，约包含Java编译/MCP与真实PG/BGE，不用skip替代。P5详细[P5计划](../phase-05-events-service/plan.md)/[验收](../phase-05-events-service/acceptance.md)。工程Gate通过后按原约定创建下一阶段GPT-6 Astra/high本地任务，持续推进，个人练习不阻塞。
