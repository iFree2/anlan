# 人员三能力实施计划

设计门禁：2026-11-22 总窗口确认通过。范围仅人员三能力，作业票不实施。按现有共享工作区独占文件执行，不建分支、不提交。

**Goal:** 可信宿主对象关系与类别授权冻结后，经同一 Registry/Policy/Executor/SDK/审计执行三能力。
**Architecture:** personnel.py 负责策略、解析与冻结；external_inquiry_personnel.py 负责独立循环；模型复用既有 scripted 协议，所有远程调用仍只在既有执行器 handler 中。
**Tech Stack:** Python/Pydantic、官方MCP SDK、PostgreSQL、pytest、Ruff。

- [x] 写 test_dynamic_mcp_personnel.py：有效承包商/人员/类别三分离、重名显式ID、关系和权限、来源冲突、冻结。运行 pytest 观察缺模块断言 RED；实现 personnel.py 后 GREEN。
- [x] 写 test_dynamic_mcp_personnel_inquiry.py：能力覆盖/引用/partial/unknown/参数篡改；运行 RED。新增独立工作流与 scripted 模型，运行 GREEN。
- [x] 写 test_dynamic_mcp_personnel_e2e.py 和新合成fixture：真实 SDK/隔离PG三wire与receipt/任务不变、异常证据及恶意动作零wire。运行 RED/GREEN。
- [ ] 独立审查首包源码/测试；修复复现问题后人员/设备/执行/合同/旧工具定向回归、Ruff和diff检查。
- [x] 更新 report.md 和文件hash清单，冻结交总窗口复验。不SSH/部署/真实模型调用。

核心命令：`uv run --no-sync pytest -q tests/test_dynamic_mcp_personnel.py`；人员全部测试使用 Python pytest.main 枚举新文件并设置显式隔离测试DSN。期望0失败、0错误、0跳过。日志保存本包 .runtime 私有目录，报告只记去敏证据。

验证门禁：本包55项全部通过，独立审查关闭；完整相邻338项有4项冻结旧链失败，故整体验收checkbox保留未完成，交总窗口复验。
