# P13 B3 实施交接

日期：2026-10-29。基线 `f5921be`；本批仍只做本地 SYNTHETIC 流程，不访问云端、不调用真实模型。

## 交付范围

- 双角色可通过独立会话读取同一申请和作业前依据投影，私聊与对方私聊隔离。
- 申请人可从服务端授权目录确认单人员、单资质类型和单区域；缺省选择为空，不由姓名或模型猜测 ID。
- 安全人员可查看对象、材料/绑定/预核查版本、查询时间、来源观察与有效期、人员资质及区域业务状态、知识引用、缺口/异常和当前性。
- 安全人员必须结构化勾选本轮引用并填写人工结论；普通聊天或模型提案不能代选引用。确认卡片冻结申请、材料、绑定和 check 版本。
- 事件生成与复核读取当前申请绑定；换绑定后旧事件复核标为 `stale_binding`，原始报警保持 `active`。
- `complete_review` 的通用入口在 required 预核查任务中由结构化引用确认入口替代；缺口/异常不能靠按钮禁用或文字绕过，服务端继续执行完成门控。
- private legacy 任务保留原 profile 事件路径；persisted collaboration 任务绝不回退 profile 默认对象。

## 本轮修复

相邻回归曾偶发 404：首个提交确认响应的 precheck 只有绑定、没有 check/evidence，后台很快生成首批依据后，`validate_cached` 把 `None -> check_id` 误判为授权变化。

修复仅限已缓存依据的批次比较：只有缓存中确实存在证据时才要求 check ID 一致。无证据的排队响应仍可幂等重放，后台完成不会被误报为撤权。

真实 RED：`tests/test_preflight_conversation.py::test_replay_of_queued_preflight_remains_idempotent_after_evidence_exists`。修复前得到 `AccessDenied`，修复后通过；相邻提交确认重放也通过。

## 验证

- B3 指定组合：74 passed，0 failed，253.03s。覆盖 API、对话、事件、Console、Perception 和 demo token。
- 协调既有组合：7 passed，0 skipped，56.13s；保留原始记录 `.runtime/p13-b3-coordinator-restored.xml`。
- Node DOM：1 passed，验证空目录选择、草稿保留、版本冻结、引用选择和 identity 清理。
- Ruff：`src tests scripts` 全部通过。
- 两隔离浏览器使用不同角色配置完成异常补充闭环：
  - 初始绑定 `worker-p13-alert` / `area-p13-restricted`，界面显示 `worker_not_current_active`、`area_not_current_normal`，无完成入口；
  - 安全人员提出补充要求；
  - 申请人换为 `worker-p13-normal` / `area-p13-normal` 并重提，绑定 v2；
  - 新预核查 ready，安全人员选择本轮引用并完成，申请 v5、材料 v1；
  - 同申请生成气体异常事件并核查，界面显示“核查完成 · 当前有效”和“原始报警 active”。

截图：

- `evidence/b3-browser-abnormal-closure-event.png`
- `evidence/b3-browser-event-review.png`

本机实际服务使用 PostgreSQL 17 / `127.0.0.1:55432` 的隔离库；截图和本文件均不包含令牌、DSN 或密码。此前正常闭环截图 `evidence/b3-browser-event.png` 保留。

## 限制与后续

- 固定业务时钟仅用于可重复演示，不代表真实时效验证。
- 本批没有验证 mobile、wheel 离源码、实际部署、真实企业平台或模型泛化；这些属于 B4/后续发布 Gate。
- 当前目录仍为 SYNTHETIC；材料核查完成仍不等于正式审批、许可或开工授权。
- B4 应执行完整非 live 回归、真实 PG 并发/恢复、wheel 资源与离源码进程重启、桌面及 390×844 布局，并更新 P13 验收与新手脚本。
