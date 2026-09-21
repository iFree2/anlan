# R1职责分包交接

2026-09-22。基线f5be259；用户要求的独立分包包已实现并验证，随后恢复P4-WP03工程Gate。没有新业务功能、模型请求或schema/checkpoint迁移。P5尚未启动。

入口为[目录/映射/验证报告](package-layout-report.md)、[ADR009](../decisions/009-responsibility-packages.md)、[模块映射](module-map.json)。内部规范包为interfaces/workflows/llm/knowledge/memory/context/tools/infrastructure/common；只保留5个旧CLI薄转发，console与python -m anlan不变。MCP子进程用interfaces.mcp_server，旧mcp_server真实握手仍验过。

最终297测试（34真实PG、0跳过）、P3冻结8/9/24、P2冻结11/11、P4三路9行与单/双角色6行替身、3例Java/MCP旧PG任务整链、wheel离源码全部导入/5资源/6CLI均通过；ruff/uv lock通过，预算30→30。独立AI只读审查未发现P1/P2问题，补齐了conninfo/serializer符号改名表。

原14文件32行用户中文注释/docstring已移动至16个新路径，逐行映射在[user-change-map](user-change-map.json)，备份在.runtime/refactor-backup；这些改动只在工作区，不混入结构提交，.idea未提交。265历史/冻结/资源文件SHA保持；WP03在途verification总结于基线提交前完善，原始XML/JSON/trace未改写。

环境：用户的`uv run anlan chat`仍在运行，不要终止以方便安装。入口exe被占用，使用`.venv/Scripts/python.exe`或`uv run --no-sync`；旧console实测可运行，wheel已构建。PG/Jaeger新shell分别加载Env，BGE缓存仍.runtime/embeddings。不要把skip当通过。

恢复路线图：P4-WP03实现已在f5be259保存且重构后17 Java/MCP边界与3整链回归通过；下一步冻结P4工程Gate、更新阶段验收/status/矩阵/学习/handoff/P5计划，通过后按授权同目录创建GPT-6 Astra/high P5任务。沿用长期自动推进约定，不等练习或常规确认。
