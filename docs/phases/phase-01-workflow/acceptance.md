# P1 验收

2026-09-20：**P1工程Gate通过**，范围与限制见 [Gate报告](evidence/wp04/gate-report.md)。个人掌握仍待验证；代码通过不等于本人掌握。

## WP01

- [x] `uv sync --locked`，`uv run pytest -q`（29 passed），`uv run ruff check .`。
- [x] `uv run anlan demo` 展示完整离线补充路径；`uv run anlan chat` 支持交互补充。
- [x] 一份合成申请缺位置/方式 → 追问 → 局部补位置，另一缺项仍在 → 再补方式 → 待人工复核；revision 单调且未填字段不丢。
- [x] 非法字段/类型/旧 revision、其他租户或用户不能修改任务；验证恢复不重做前一个分析节点。
- [x] 规则模式标明语义未核查；HTTP 替身验证模型合法、无效输出、超时分别有处理；Schema 合法不能声称内容正确。
- [x] 轨迹可关联任务和本轮，错误不泄露凭据/响应正文；日志写失败显示缺口，流程仍可继续；模型失败保留版本。
- [x] 真实请求小样本联调：2026-09-20三次、无重试、1184 token，用量完整；逐例结果见 [WP03报告](evidence/wp03/final-report.md)。
- [ ] 本人完成一次小改动/故障定位并解释 3—5 个问题，记录在 learning-log。

功能证据见 [WP01](evidence/wp01/verification.md) / [WP03](evidence/wp03/final-report.md)。本人掌握仍待验证；按用户2026-09-20要求，学习项独立记录，不阻塞继续编码，不能因为AI跑通而勾选。

## WP02 与 Phase Gate

- [x] 官方 PostgreSQL checkpoint；独立CLI进程续接、分析中硬退出恢复及数据库重启，保留输入/版本。[WP02证据](evidence/wp02/verification.md)。
- [x] 重复/过期恢复与归属边界；SQL查询运行记录；跨进程争用/丢锁拒写；模型结果保存前硬退出可能重复调用，未宣称exactly-once。
- [x] 三例模型dev与八例冻结工程回归分开；原始结果/失败保留；均注明已见，未将旧holdout当未见测试。
- [x] WP04完整PG路径、56项测试与冻结工程回归通过；历史模型结果单独呈现；已检查本人证据，未勾成掌握。
- [x] 收拢P1主计划为工作包索引，保留历史计划/原始结果；[阶段handoff](handoff.md)包含目标、交付、版本、命令、风险与P2入口。
- [x] 更新status/roadmap，准备P2 plan/acceptance；按用户原约定在同目录新建GPT-6 Astra/high任务冷启动。
