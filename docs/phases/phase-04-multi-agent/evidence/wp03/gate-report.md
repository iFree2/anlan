# P4阶段工程Gate：通过

2026-09-22。范围是受控事实/知识双分支、独立风险/证据复核模型职责、固定协调、Java两只读API/MCP和R1职责包；不是模型语义质量或个人掌握通过。

| 验证 | 实际结果 |
|---|---|
| 全量回归 | R1最终297 passed、0 skipped，34真实PG：[XML](../../../../refactoring/evidence/pytest-final.xml) |
| 新Gate验真负例 | 2 passed，缺角色/隐蔽请求/根候选被篡改/桥比较失败不得假通过：[XML](gate-unit-final.xml) |
| P4冻结Gate，python -O | 9串并行行、6单/双角色行、3真实Java-MCP整链、2跨进程CLI、61故障测试及账本不变均通过：[gate-final.json](gate-final.json) |
| 原P3冻结回归 | 8上下文/9综合策略/24进程Memory通过：[报告](../../../../refactoring/evidence/p3-regression.json) |
| 原P2冻结回归 | 11/11，真实Jaeger/BGE且新请求0：[报告](../../../../refactoring/evidence/p2-regression.json) |
| 打包/命令 | wheel离源码全部模块导入、5原字节资源、6新旧CLI，原anlan.exe与旧MCP真实握手通过：[R1](../../../../refactoring/package-layout-report.md) |
| 静态/依赖 | ruff、compileall、uv lock --check通过；SDK1.30.0/JDK21，Java真实编译/运行 |
| 模型效果与成本 | 本阶段仅WP02真实9请求/22461token；单模型接受2/3，双角色risk接受3/3但复核2异议，成本/延迟增加：[报告](../wp02/live-report.md) |

冻结输入沿用P3同任务、知识/事实、时点与指引SHA，`evals/phase04-regression-v1/manifest.json`独立记录。Gate验证代码不用assert，优化模式下仍校验；子pytest仅证明故障边界，不能充当模型质量评测。所有输出新路径，历史工件/失败不覆盖。

保留不足：WP01两例并行更慢；双角色多95%token/约74%模型阶段延迟；审核最小上下文缺材料，漏查位置映射/离题引用；材料说明缺引用类型依旧。R1是结构改进，不改变这些语义事实。本人掌握待本人证据，AI检查不是独立人工金标。

生产PG账本累计30/100，P4-WP02=9/10、P3-WP03=9/10、P2两包各6/10，全部succeeded无未知reserved；本Gate30→30。总已知新授权62744token，P1历史1184另列。每包10/累计100是保守次数上限，不是金额预算，不得重复完整9请求实验。

阶段提交链：fb3eef2双分支、f4c4a47两角色、f5be259 Java/MCP基线、d7b56d8独立R1分包。最终阶段提交另记录Git历史。原14文件32行用户译文现16路径仍未提交，.idea保留。进入[P5](../../../phase-05-events-service/plan.md)首包模拟事件，首先零模型请求。
