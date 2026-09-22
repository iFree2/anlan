# P5-WP02：工程通过；真实模型0/2接受

2026-09-22，基线b035589。[设计](../../wp02-plan.md)/[ADR012](../../../../decisions/012-material-revision-and-perception-review.md)。P5阶段Gate尚未通过，WP03服务/清洁启动仍待实施。

| 验证 | 实际结果 |
|---|---|
| 全量 | [pytest-initial.xml](pytest-initial.xml) 382 passed、0 skipped，74真实PG；之后新增字段诊断与报告验真各1项通过，累计384；后改字段诊断的21项专项见output-diagnostics-green.xml |
| 显式材料revise | 6新真实PG用例＋原恢复共22通过：[revisions-green-initial.xml](revisions-green-initial.xml)，三个崩溃窗口不二次合并，等待输入/越权/mode/旧版本/跨方法ID拒绝 |
| 取消与并行回归 | [cancel-races-green.xml](cancel-races-green.xml) 54项通过；涵盖模型信号/子清理竞态、父取消＋材料变更、部分证据保留与原P4 collector |
| 两类工程整链 | [scripted-v2.json](scripted-v2.json)：真实BGE/PG、三观察ok、两条事件→候选→跨进程模拟反馈→revise→stale→新绑定事件重核；首轮scripted-v1子进程失败保留 |
| 真实模型 | [live-report.md](live-report.md)/[live-v1.json](live-v1.json)：2 failed/5072token，0/2应用接受；报警/证据保留，后续重核是明确替身，不能作为真实成功 |
| CLI | [cli-green-initial.xml](cli-green-initial.xml)：实际anlan revise＋perception review/show/feedback跨进程 |
| 旧P4 Gate | [p4-regression.json](p4-regression.json)：9/6/3/2路径及61故障全通过，含实际Java/MCP、账本32→32 |
| 包/依赖/静态 | [wheel-final.json](wheel-final.json)：离源码导入、8资源字节/8CLI，ruff/uv lock通过 |
| 独立只读审查 | 发现两项取消缺陷及其窄竞态，均已复现、修复、本人运行验证；最后取消专项9通过，审查未发现该范围残余实质问题。AI检查不等于本人掌握 |

失败保留：新增能力红测；attempt-attribution-red（未发请求错归上次attempt）；model-cancel-red和cancel-races-red（模型取消漏检、材料变更覆盖取消并丢证据）；scripted-v1（Windows Selector不支持asyncio子进程，已改线程内subprocess.run）；CLI缺入口；wheel-initial固定旧资源数；output-diagnostics-red（缺type/loc诊断）。真实invalid_output无法回溯具体字段，后续诊断仅替身验证，无追加真实请求。

边界：候选只含有限分类/引用/人工步骤，没有控制命令和批准字段；依然不能证明事件真实或模型语义。feedback在演示中由合成角色提交，不是用户本人现场确认。合作式取消不宣称强杀阻塞扩展。任务/事件/结果同锁写入有真实PG验证，数据库不可用时仍可能留下pending，显式recover不重发模型。

预算现在32/100，P5-WP02=2/10且均failed，无reserved；失败消耗上限。已知新授权67816token，P1历史1184另列，金额未知。原始报警均active；未改变旧P2/P3/P4冻结数据/报告。用户32行译文仍须保持unstaged。
