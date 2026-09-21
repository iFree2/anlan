# ADR009：职责分包，保留业务合同与命令兼容

2026-09-22。用户在P4-WP03在途时明确要求按职责分包；先保存f5be259（291项测试、17 Java/MCP边界与3真实PG整链），再执行独立R1结构包，无新模型请求。

采用interfaces/workflows/llm/knowledge/memory/context/tools/infrastructure/common浅层包。共享层只有StrictModel/Identity/NonEmpty及通用错误；材料、知识、记忆、review合同靠近各自功能。__init__只有说明，不做批量重导出或隐式装配。相对机械三层/全塞domain，这样保留具体功能入口和依赖可读性。

`infrastructure/db.py`只提供database_url与conninfo，不导入WorkflowService。`infrastructure/postgres.py`实现Registry/serializer/setup，`interfaces/runtime.py`装配材料工作流。Registry与Saver仍使用同一个连接；原advisory锁、丢锁拒写、受限serde、schema/checkpoint合同与SQL均未改变。

Memory枚举与Feedback/MemoryConflict移至纯contracts；context只依赖此合同，不加载PG。KnowledgeCitation从含模型适配器的tool_model抽到knowledge/contracts。AnalysisFailure归llm/contracts，供应商配置单独放llm/config。review模型适配与宿主采集/综合分离；两个角色的提示、合同校验、请求次数、包号与模型行为保持原样。

旧CLI仅保留五个薄转发模块：cli、memory_cli、review_cli、multi_review_cli、mcp_server；anlan与python -m anlan保持。内部import与测试monkeypatch统一指向规范模块，不为所有内部模块保留永久双结构。MCP子进程切interfaces.mcp_server，旧mcp_server的真实握手也有回归。内部Python路径不承诺永久兼容。

SQL/assets继续放包根并使用files('anlan')；旧冻结JSON及原始报告不改。eval/script文件保留位置但改imports，新运行自然记录新的runner_sha256，不能改写历史摘要来冒充同一运行器。wheel离源码导入、资源字节与入口均实测。

移动的是用户当前工作树；原14文件32行译文逐行匹配到新路径并备份。提交仅在index隔离这些译文，工作树保留，.idea不提交。[模块映射](../refactoring/module-map.json)、[用户改动映射](../refactoring/user-change-map.json)、[验证报告](../refactoring/package-layout-report.md)为验收依据。此包不引入通用harness、框架迁移或新业务功能。
