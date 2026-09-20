# P2阶段交接（含WP05）：工程Gate通过

结束日期：2026-09-21。依据[最终Gate与原始证据](evidence/wp05/gate-report.md)。用户已长期授权按路线图自动推进；下一任务同目录启动P3，直接实施首包，不等待常规范围确认或练习答案。个人掌握与模型泛化仍待验。

## 当前可以运行什么

P1材料四字段→规则/可选模型→interrupt追问→补充/revision→再分析→待人工复核仍由LangGraph保存。PG registry/checkpoint/同连接任务锁与pending恢复保留，P2没有改写材料生命周期或新增批准字段。

P2增加两个真实读取版本化SYNTHETIC JSON的只读工具。`check-facts`固定查询；`check-facts-agent`模型提出白名单动作，代码校验参数、入口对象范围和身份，反馈观察并有界停止。可选`--knowledge-question`增加第三工具，查询本地中文BGE/512维与pgvector中的授权、有效、未撤回当前文档；最终引用必须出自本轮片段原文，摘要仍是未验证候选。

知识摄取/升版/撤回属于本地合成库管理：每文档事务、owner修改、同版本变内容拒绝、撤回不静默复活。CLI模拟身份不是生产认证。简单向量与混合重排都有真实对照，默认vector，因为本集没有混合收益。

模型请求先在唯一PG账本持久预占，再发HTTP；失败/未知仍占用。Jaeger通过可选本地OTLP接收既有JSONL事件，run对应trace，task/correlation是关联属性，模型/工具及知识来源可追踪。导出失败显式告警而不丢业务结果；JSONL不保存原始材料、凭据或隐藏推理，导出属性有白名单。

## 模块与决定

- `tools/`、`facts.py`：事实合同、授权/时间/错误与固定查询。
- `tool_model.py`、`tool_loop.py`、`knowledge_tool.py`：模型动作/观察/停止与知识引用校验。
- `budget.py`、SQL002、`live.py`：项目共享预占；P1材料真实入口也受此约束。
- `embeddings.py`、`knowledge.py`、SQL003：固定本地模型文件摘要、知识版本与过滤/检索。
- `trace.py`、`telemetry.py`：JSONL与可选OTLP；`scripts/dev-jaeger.ps1`管理项目独立平台。
- [ADR001](../../decisions/001-workflow-state.md)/[ADR002](../../decisions/002-postgres-recovery.md)保留状态/恢复边界；[ADR003](../../decisions/003-model-budget-and-tool-loop.md)预算与循环；[ADR004](../../decisions/004-synthetic-knowledge-retrieval.md)知识；[ADR005](../../decisions/005-local-observability.md)追踪。

## 环境与复现

同目录 `D:/src/agent学习/安澜2.0`，当前分支沿用work/phase-01-wp-04。Python3.13、依赖锁uv.lock；fastembed0.8.0，本地BAAI/bge-small-zh-v1.5；项目PG17.11在127.0.0.1:55432，系统PG10未改。pgvector0.8.6使用固定SHA的非官方社区Windows包，来源和验证在安装证据中，不能称上游官方二进制。

```powershell
uv sync --locked --link-mode copy
.\scripts\dev-postgres.ps1 -Action Start
uv run anlan db-init
uv run python scripts/install_pgvector.py
uv run python scripts/install_jaeger.py
.\scripts\dev-jaeger.ps1 -Action Start
# 新终端需重新加载两个Env；Jaeger脚本要求PowerShell7
.\scripts\dev-postgres.ps1 -Action Env
.\scripts\dev-jaeger.ps1 -Action Env
uv run python evals/phase02_gate.py --output .runtime/p2-new-check.json
```

Jaeger为官方2.21.0，UI `http://127.0.0.1:16686`、OTLP4318；服务列表API已改`/api/v3/services`，单trace兼容`/api/traces/{id}`。仅回环监听、内存最多1000 traces，重启会丢展示；本地JSONL与证据文件保留。导入旧轨迹用`import_trace.py`，会生成独立archived_import trace，不执行模型/工具，不补造未记录耗时。

本地模型缓存/manifest在`.runtime/embeddings`，模型凭据仍是用户指定且Git忽略的`docs/DS.txt`，不可输出。PG凭据由项目Env脚本加载，不打印。默认实时查询会受示例有效期影响：area-001在2026-09-21T00:00:00Z（北京时间08:00）后过期；复现实验使用明确的`--as-of 2026-09-20T12:00:00Z`，不要擅自改冻结记录日期。

## 验证与余额

最终185测试（含26真实PG场景）、P2冻结11场景、优化模式下的两条实际平台链通过；P1冻结回归及各包演示保留。WP05没有新真实模型请求，Gate前后账本均12。

生产授权`20260920-long-term-v1`，PG `model_budget_authorizations/model_budget_attempts`是唯一账本。新授权累计12/100，WP02与WP04各6/10，已知19818token；P1历史三次/1184token单列。每包最多10、累计100是已告知用户的保守执行上限，不是金额预算；失败/未知预占均计数，无退款/重置。新实验前读即时账本，不能把JSON快照当可单独续增的第二账本。

注意当前DeepSeekToolModel按include_knowledge固定映射P2-WP02/WP04，材料分析默认P2-WP02。P3先将新实验包号接到可信入口并测试，再请求，不能误占旧包或先调用后改账。仍只用deepseek-flash及既定端点，无自动重试，不扩大价位/供应商。

## 未解决项与下一步

WP04第2例存在未显式引用次要片段的摘要主张；所选quote有效不等于全部语义有依据。真实样本均已见，不是独立泛化证据；混合检索无收益结果保留。PG一次非正常退出原因未确定；默认内存材料/Jaeger均不是持久业务恢复。生产认证、最终任务修订/取消、Memory、多Agent、事件和服务化尚未完成。

P3读取[plan](../phase-03-memory-context/plan.md)与[acceptance](../phase-03-memory-context/acceptance.md)。首包为用户作用域的合成偏好/反馈候选及确认、拒绝、修正、过期、删除、冲突；先真实PG和CLI，不需模型调用。不能用记忆替代当前资质/区域事实或改变权限，也不要重建已通过的Graph/PG/工具。

保留原14个文件的中文注释/docstring修改与.idea，不回退或擅自提交；每次本包提交均将这些修改留在工作区。所有AI实现/审查/测试只算工程证据，个人掌握继续待验。协调任务有30分钟自动续接，不另建重复自动化，不并行改正在运行任务的代码。
