# P12 双角色材料核查协作

用户已确认实施：申请人和安全管理人员独立身份、各自独立会话，共享同一申请；仅做到材料核查完成，不做正式审批和开工授权。先整理文档，每批在各自Codex会话串行实施，最后部署并录制真实双角色视频。

- [已确认设计](../../superpowers/specs/2026-10-22-dual-role-collaboration-design.md)
- [分批实施计划](../../superpowers/plans/2026-10-22-dual-role-collaboration.md)
- [验收清单](acceptance.md)

## 批次状态

| 批次 | 范围 | 状态 | 会话/交接 |
|---|---|---|---|
| B1 | 身份角色、合同、权限策略、协作PG存储 | 已验收：186 passed / 0 skipped，Ruff通过，无审查阻塞 | [实施交接](batch-01-handoff.md)、[协调复核](batch-01-coordinator-check.md)；会话 `01a1642e-89bb-7533-a455-01a553fee50f` |
| B2 | 后端共享任务授权、提交/退回/重提/完成、通知 | 协调回归268 passed；通知并发游标问题修复中，未验收 | 独立会话 `01a16446-0f18-76b1-abc4-38cd19560d66`；[协调检查](batch-02-coordinator-check.md) |
| B3 | 两角色对话/任务侧栏、事件核查授权 | 等待B2验收 | 尚未创建 |
| B4 | 全套与双浏览器、异常恢复、wheel验证 | 等待B3验收 | 尚未创建 |
| B5 | ECS发布、有限live联调、双角色视频 | 等待B4验收 | 尚未创建 |

本页的“文档已完成”不等于功能完成，所有Gate以实际测试/录制证据为准。首次设计记录时未改业务代码、未SSH、未调用业务模型。

## 协调纪律

- 当前总协调会话是“调研行业 Agent 案例”；各批只执行本批，不自行创建后续会话或扩大范围。
- 不并行改同一检出。每批完成后协调检查commit、变更路径、实跑测试与交接，再启动下一批。
- 不动用户原有未提交路径：docs/roadmap.md、docs/status.md中的P10段落、docs/phases/phase-10-dynamic-mcp/、tests/test_tool_loop_live.py、.superpowers/。
- 不把凭据或连接配置放进文档、会话提示、视频或Git；不打印私密配置值。
- 第四批前不部署、不调用真实模型；第五批先核对余额，沿用现有上限，额度不足另问用户。
