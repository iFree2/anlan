# P2-WP04交接：材料、事实与知识的同一受控链路

2026-09-20。工程包通过，进入WP05追踪平台与P2 Gate；个人掌握独立待验，长期自动推进授权不变。

`check-facts-agent`增加可选`--knowledge-question`。提供时启用第三只读工具query_knowledge，问题逐字绑定入口，身份由宿主注入；原两个事实工具与旧调用不变。3回合/4动作/75秒限制保留，知识错误或初始化失败仍保留事实结果。最终knowledge_citations必须对应本轮chunk及连续原文；无知识结果不能造引用。模型摘要仍未验证，不改P1材料或审批状态。

验证：[159项全量](evidence/wp04/pytest-final.xml)通过（含原26真实PG场景），新增2个评分器边界测试也通过；[4命令跨进程CLI](evidence/wp04/cli-smoke.json)与[P1冻结8例25步](evidence/wp04/p1-regression.json)通过，ruff通过。独立[规格/质量审查](evidence/wp04/review.md)发现的知识失败丢报告问题已先红后修复。

真实3例整合任务：[原始结果](evidence/wp04/live-v1.json)、[逐句核对](evidence/wp04/live-report.md)。各2次请求，共6次/12535token；工具结果与所选原文引用符合当前已见标注。**过期案例存在摘要主张未显式引用对应次要片段的Badcase**，不能宣称全摘要依据充分。保留候选及限制，不追加请求掩盖问题；工程成功与摘要语义分开。

唯一项目PG账本当前P2-WP02=6、WP04=6，总12/100；本包6/10，全部完成，无pending。新授权累计19818token，P1历史三次/1184token单列。不能重置或把每个新任务另计总预算。

复现离线整合：先按README准备PG/pgvector/本地模型，`uv run python evals/evaluate_rag.py --output .runtime/rag-scripted-new.json`准备独立合成租户并运行明确替身；再`uv run python scripts/smoke_rag.py --source-report .runtime/rag-scripted-new.json --output .runtime/rag-cli-new.json`验证跨进程。真实实验查看已有档案即可，重复真实模式会占额。

下一包优先完成本地可运行的一种追踪平台。已核实Langfuse本机部署需Docker，本机无Docker/WSL/管理员；Jaeger2.21提供官方Windows单二进制与OTLP，拟用它完成模型/工具/检索来源诊断，不冒称拥有Langfuse的LLM专属功能。平台安装不是验收，需要真实span查询、失败定位及导出失败保留证据，再做P2冻结Gate与阶段交接。
