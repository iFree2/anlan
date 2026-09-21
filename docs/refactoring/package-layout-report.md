# R1职责分包：结构、兼容与验证

2026-09-22。基线f5be259。按用户要求在P4-WP03安全收束后独立实施；未启动P5、未请求真实模型。32个顶层实现模块移入职责包，抽出11个连接/合同/模型/入口单元，根只保留包入口和5个兼容命令模块。

```text
src/anlan/
├─ common/          models, errors
├─ interfaces/      cli, memory_cli, review_cli, multi_review_cli, mcp_server,
│                   fact_http, runtime
├─ workflows/       material_contracts, material_analysis, materials, service,
│                   registry, evaluation, facts, tool_loop, review_contracts,
│                   review, parallel, multi_review
├─ llm/             config, contracts, material, gateway, tool_model,
│                   review_model, evidence_review
├─ knowledge/       contracts, store, embeddings, tool
├─ memory/          contracts, store
├─ context/         assembly
├─ tools/           contracts, queries, http_client, mcp
├─ infrastructure/  db, postgres, budget, live, trace, telemetry
├─ sql/             001—004迁移（原位、原字节）
├─ assets/          hot-work-review-v1.md（原位、原字节）
└─ __main__ + 5个兼容CLI（不重导出所有旧内部模块）
```

完整旧新文件/符号表：[module-map.json](module-map.json)。包括_conninfo→conninfo、_serde→checkpoint_serde。迁移前依赖：[dependencies-before.json](dependencies-before.json)。共享异常只有一个类定义；上下文不再间接加载PG，数据库配置不再装配工作流。具体取舍见[ADR009](../decisions/009-responsibility-packages.md)。

## 实际验证

| 检查 | 结果与工件 |
|---|---|
| 原基线 | 291通过、34真实PG：[WP03基线](../phases/phase-04-multi-agent/evidence/wp03/pytest-baseline.xml) |
| 迁移全量 | 最终297通过（34真实PG、0跳过）：[pytest-final.xml](evidence/pytest-final.xml)；首轮296亦保留。包含PG断连/丢锁、跨进程崩溃回执/恢复、预算、知识/Memory与Java/MCP |
| 轻量导入与兼容MCP | 6通过：[layout-final.xml](evidence/layout-final.xml)，实际旧MCP命令握手/call成功 |
| P3冻结回归（-O） | 8上下文/9综合策略/24进程Memory通过：[p3-regression.json](evidence/p3-regression.json) |
| P2冻结回归（-O） | 11/11含Jaeger/BGE通过，新请求0：[p2-regression.json](evidence/p2-regression.json) |
| P4同集替身 | 三路采集9行、单/双角色6行完成：[parallel-regression](evidence/parallel-regression.json)、[multi-regression](evidence/multi-regression.json) |
| 原任务真实Java/MCP整链（-O） | 3例直接/跨语言证据相同、两角色替身完成、材料未变、预算30→30：[java-mcp-regression](evidence/java-mcp-regression.json) |
| wheel | 构建成功；离源码目录导入全部模块、5资源字节一致、6新旧CLI帮助成功：[wheel-final](evidence/wheel-final.json) |
| 已有Windows console | 原anlan.exe无需重装即可执行--help，不结束用户chat：[existing-launcher](evidence/existing-launcher.json) |
| 原始工件与用户改动 | 265历史/冻结/资源文件摘要一致；原14文件32行译文全部找到新归属：[preservation](evidence/preservation.json)、[user-change-map](user-change-map.json) |

运行命令采用`.venv/Scripts/python.exe`（pytest、-O各回归脚本）；PG先`dev-postgres.ps1 -Action Env`，P2另加载`dev-jaeger.ps1 -Action Env`。构建`uv build --wheel --out-dir .runtime/refactor-dist-final`，验证`scripts/verify_package_layout.py --wheel <wheel> --output <new.json>`，`uv lock --check`。已有chat占用exe时不执行重装入口，ruff用`uv run --no-sync ruff check .`。

## 失败与审查

新布局6项红测先证实尚无新包；其中一项源码字符串检查后来移除，由已有真实PG丢锁测试承担行为验证。初次局部迁移65通过、1失败：批量迁移误把新测试的包导入`from anlan.knowledge import store`改成`from anlan.knowledge.store import store`，修正为明确模块导入；原XML保留。抽取后的未使用import、长行与pytest共享fixture lint已逐项处理，只整理import/抽取空白，不大范围重排业务代码。

独立AI只读审查：20项定向通过、内部import图无环、__init__轻量；按映射比较基线顶层类/函数AST，忽略docstring及连接辅助函数改名后，仅MCP子进程规范路径存在预期变化。未发现P1/P2阻断；指出符号改名表缺失，已补new_symbol与serializer映射。此审查不是本人实践或独立人工金标。

## 保护与限制

用户完整备份在`.runtime/refactor-backup`；源文件按当前worktree移动，中文译文没有从HEAD覆盖。原14文件32行现对应16个目标文件。提交前index单独恢复其英文基线，仅提交结构/import调整；用户译文留作新路径unstaged改动。历史原报告、冻结数据、SQL和指引没有重写；运行器代码更新与新证据分开记录。

公开兼容范围是命令与业务/数据库合同，内部Python导入路径统一迁移。不把结构清晰当模型质量提升，也不升级个人掌握。P4阶段Gate仍需按路线图收尾；真实模型预算保持30/100，不重复P4-WP02已占9/10的实验。
