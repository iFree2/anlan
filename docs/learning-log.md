# 学习记录

只记录本人亲自完成并经检查的实践，不以 AI 实现代替掌握。

| 工作包 | 本人实践 / 讲解证据 | 掌握情况 |
|---|---|---|
| P1-WP01 | AI 已实现离线基线并验证；本人尚未提交修改、排错或讲解证据 | 待验证 |

本轮要理解：
1. TypedDict 与 Pydantic 各在哪个边界起作用？对应 Java 的哪些概念？
2. 为什么 analyze 和 ask 分成节点？resume 会重新执行哪一段？
3. 字段补充如何合并、revision 如何防止旧输入覆盖？
4. 无缺项、模型结构有效、人工复核分别能证明什么？
5. task/thread/run/tenant 如何区分；为什么知道 thread_id 不代表有权限？

本轮练习（本人完成）：修改 `src/anlan/contracts.py` 中 `QUESTIONS` 的“作业方式”追问，让它说明需要提供何种信息但不暗示某个安全/合规答案；在 `tests/test_workflow.py` 加入一个对应行为断言，运行 `uv run pytest -q` 和 `uv run anlan demo`。请本人提交改动及解释，导师不代做，不提前标记掌握。

可参照但不能记作本人实践的 AI 排错：trace 文件不可写令图在补充后卡住；先用目录当日志路径复现，再将 OSError 转为显式 trace_warning，保持后续补充可用。该回归测试由 AI 编写，本人的独立定位能力尚未验证。
