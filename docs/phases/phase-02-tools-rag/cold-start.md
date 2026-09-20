# P2冷启动核对与首包范围建议

日期：2026-09-20。状态：核对完成，P2-WP01待用户确认，尚未实现。按用户要求直接使用同一项目目录；未创建worktree、切分支或提交。

## 仓库与历史证据

- HEAD：`fc64b27`，分支 `work/phase-01-wp-04`。最近提交依次为P1冻结回归/交接、真实模型联调/学习要求、PG恢复、本人追问断言、初始材料工作流。
- 仓库及D盘至项目目录的祖先路径未发现AGENTS.md。已读产品范围、status、roadmap、P1 handoff、P2 plan/acceptance、ADR001/002、架构、能力矩阵、学习记录与相关原始证据。
- 初始14个修改文件的差异均为中文注释/docstring替换，32行替换；`.idea/`未跟踪。全部保留，未修改或提交。未读取模型凭据或旧项目内容。
- 核对P1 `pytest-final.xml`：56项，0失败/错误/跳过，含11项test_postgres；历史CLI报告9条命令、3条SQL提交记录、status=passed，PG17.11。
- 核对WP03原始JSON：3次请求、3例已见合成开发样本、3个最终问题集合相符；1126输入/58输出/1184总token。规则与模型各贡献1条命中，不能当成独立泛化证据。
- 冻结manifest和本地重评分支持P1历史报告；重评分不等于新模型请求或轨迹回放。

## 当前系统实际运行

CLI注入本地模拟Identity；service检查归属、revision和request_id；LangGraph执行analyze→ask/interrupt→局部字段合并→再次analyze。四字段齐备且无候选问题时到awaiting_review；离线模式仅查空字段，不判断语义正确或安全。

内存模式随进程结束丢失；PG模式由registry保存归属/提交，官方saver保存图状态，同连接锁阻止丢锁旧执行继续写回。pending与recover协调分步持久化，不是单事务；模型请求后保存前硬退出仍可能重复请求。本机项目PG在127.0.0.1:55432已运行，本轮仅加载Env，没有重启或调整系统服务。

当前没有工具循环、RAG、pgvector、Langfuse、长期Memory、多Agent或事件接入。身份仍为模拟，无生产认证；最终任务修订/取消和跨进程模型预算未实现。用户个人掌握独立待验证。

## 本轮最小验证

| 检查 | 新结果 | 原始证据 |
|---|---|---|
| 工作流/评测/内存恢复及两项真实PG | 24 passed，0 skipped；31.22秒 | [pytest.xml](evidence/cold-start-20260920/pytest.xml) |
| 离线CLI三轮 | revision 1/2为waiting_input，3为awaiting_review；semantic_status均offline_not_checked | [demo](evidence/cold-start-20260920/demo.jsonl)、[trace](evidence/cold-start-20260920/demo.trace.jsonl) |
| 冻结工程回归及历史重评分 | 8例/25步通过；历史3例相符；本轮请求0、token0 | [frozen-regression](evidence/cold-start-20260920/frozen-regression.json) |

实际命令（项目根目录，已有锁定环境）：

```powershell
$env:PYTHONUTF8 = '1'
.\scripts\dev-postgres.ps1 -Action Status
.\scripts\dev-postgres.ps1 -Action Env
uv run --locked pytest -q tests/test_workflow.py tests/test_evaluation.py tests/test_recovery.py tests/test_postgres.py::test_cli_restart_and_duplicate_request tests/test_postgres.py::test_incomplete_analysis_recovers_on_new_connection_without_second_merge --junitxml=docs/phases/phase-02-tools-rag/evidence/cold-start-20260920/pytest.xml
uv run --locked anlan demo --mode offline --trace docs/phases/phase-02-tools-rag/evidence/cold-start-20260920/demo.trace.jsonl
uv run --locked python evals/phase_gate.py --output docs/phases/phase-02-tools-rag/evidence/cold-start-20260920/frozen-regression.json
```

demo的stdout另保存为表中demo.jsonl。复现请使用新的证据路径，勿覆盖已有结果。本轮未重跑全量56项测试或历史9命令演示，不将历史结果冒充本轮结果。

发现一处文档偏差：architecture图原写“无待补充项或模型失败”进入人工复核；`workflow.py`实际先保留规则缺项，再依据issues路由。冻结案例p1-08先保持waiting_input，补齐后才awaiting_review，二者都保留failed。已修正文档，不修改代码或冻结期望。status中1788fdb/17项smoke属于上一包冷启动历史，已更新为本轮事实。

## P2目标、首包与退出条件

P2整体目标是查询当前合成事实、检索示例知识并提供可追溯辅助证据。整体退出还要求有界白名单工具循环、pgvector摄取/版本/租户/有效期/撤回、简单检索与一种改进对照、检索命中和依据支持分开评测、可定位来源的追踪与失败记录。两只读工具通过只完成WP01，不代表P2通过。

推荐首包：独立check-facts入口，在任务归属校验后按固定顺序执行query_worker_qualification和query_area_status，实际读取版本化SYNTHETIC JSON。身份来自入口，业务ID来自独立引用输入；结果带来源/时效/事实或未知/错误，关联任务、核验run、correlation及源材料版本，不改P1四字段或生命周期。详细接入取舍见[plan](plan.md)。

首包退出：正常、缺失、过期、不适用、非法参数、无权、超时和读取失败可解释；越权状态不变且无他租户事实泄漏；固定时钟及可复现CLI演示；P1冻结回归/关键恢复无退化；状态、证据、架构、能力矩阵、交接与学习记录齐备。没有真实模型请求、RAG安装、多Agent或通用平台。

按本次用户明确要求，在新任务收到首包范围确认后再开始实现。未因AI冷启动验证而更新个人掌握等级。
