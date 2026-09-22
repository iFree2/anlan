# P5进行中：WP01/WP02工程通过，继续WP03

2026-09-22。同目录D:/src/agent学习/安澜2.0唯一写入，沿用长期授权逐包实现/亲自验证/保留失败/更新状态后自动下一包；不等常规许可或练习。P5阶段Gate未通过，先做服务，不创建P6。

WP01提交b035589：两类SYNTHETIC事件、可信SourceBinding、SQL005原始记录/水位/一次关联结果、events_cli。原始报警先独立提交，关联锁/Saver/结果写同一连接；连接终止不能发布迟到结果。342累计验证、54真实PG、12进程回放、原P4/wheel通过，历史证据在evidence/wp01，别改写。

WP02已完成显式material revise（SQL006、同task/thread新revision/run、resume合同不变、三个崩溃窗口恢复）；感知三工具采集＋一次有限枚举模型候选、SQL007重核/反馈/运行锁、旧材料/较新事件/时效stale、perception_cli。原始报警不变，反馈不批准/改材料/控制设备。collect_parallel仅新增可选progress保留最终版本校验前已验证的观察，默认P4语义不变。

实际验证：382全量零skip＋2新增诊断/报告验真，累计384（74真实PG）；两条真实BGE/PG替身完整链；原P4冻结9/6/3/2及61故障通过；wheel8资源/8CLI，ruff/lock通过。[WP02验证](evidence/wp02/verification.md)。独立AI审查发现取消漏洞及窄竞态，均已由本任务红绿测试验证修复：模型阶段/清理后/结果选择前监听signal，父取消先汇合观察，材料变化不能覆盖原取消。未宣称任意阻塞扩展可强杀。

真实模型P5-WP02两次均invalid_output，0/2接受、5072token。原网关没有字段诊断，无法证明具体根因；已补type/loc诊断，仅替身验证，无追加请求。[原始结果](evidence/wp02/live-v1.json)/[报告](evidence/wp02/live-report.md)。其中后续材料修订重核明确scripted_double；不能美化真实0/2。合成反馈不是用户本人确认。

唯一PG授权20260920-long-term-v1累计32/100：P2两包各6、P3-WP03=9、P4-WP02=9、P5-WP02=2（failed）；其余30 succeeded，无reserved。已知新授权输入59475/输出8341/总67816token，P1历史1184另列，金额未查。失败占额度，不重置/退款/占旧包。WP03默认替身服务，无新真实模型请求。

继续WP03：FastAPI可信宿主token→identity，事件绑定来自宿主配置而非正文；暴露材料start/get/resume/revise/recover与事件/重核/反馈，SSE以持久快照支持断连/Last-Event-ID恢复，断流不等于取消业务；显式持久重核取消和进程重启恢复需要测试。实际原生清洁环境启动/基础CI，Docker未找到、WSL未安装，Compose不可用不得计部署通过。先读产品/status/roadmap、P5计划/验收/ADR002—012，沿用既有职责包，不重建图/预算/工具/Memory。

环境PG17.11:55432；每shell脚本Action Env，Jaeger独立Env。新事件/事实/知识examples/synthetic/perception-v1使用独立2026-09-22T04:00Z；旧P2/P3/P4保持2026-09-20T12:00Z等原时间不改。用户chat可能占anlan.exe，使用.venv/Scripts/python.exe或uv run --no-sync，不杀进程。

原16路径32行用户译文及.idea保留unstaged，映射/备份仍在docs/refactoring/user-change-map.json及.runtime/refactor-backup。本包修改含译文的service/postgres/cli，提交时只stage自己的变化；不能整文件混入用户译文。协调任务01a0b000-4960-7571-b6ea-e952a22bbd16只读跟进，已有30分钟自动化id=2-0，勿重复创建或并行改码。
