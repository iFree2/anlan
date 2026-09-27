# WP02：离线质量闭环与合同留出

2026-09-27。manifest冻结SHA见[corpus](../../../../../evals/quality-v1/README.md)，11项均合成：开发6、合同留出5，标签由AI构造可逐项核对，非独立人类金标/模型泛化集。原P5与WP01同源真实记录全部在开发。

闭环：合成离线争议反馈dev-duplicate → 明确Badcase（unknown IDs重复）→ 集合比较丢失重复信息的可复现归因 → 增加长度一致约束 → 开发回放5/6到6/6标签匹配。原模型失败的字段根因仍not_established。开发中两项是not_replayable，只有状态符合预期，不能算模型成功。新两个真实输出在更严格验证器下仍接受，但这是录制回放，零新请求。

冻结合同留出首次[holdout-once.json](holdout-once.json)5/5标签匹配，涵盖全部未知、waiting_input补材料、错事件、控制步骤和未知遗漏。不是5次模型正确回答；只验证记录中给定候选的验收。看到结果后该组已经已见，没有再调合同规则或重跑刷分。

只读inspect输出来源SHA/run/反馈来源与枚举，不重新查事实。replay仅重验录制候选，源无输出保持不可回放。真正复跑沿用既有有预算的明确实验入口；CLI没有隐式live/rerun选项。真实业务反馈来自PG；这里的synthetic_dataset_annotation仅离线标注，不写PG，也不把needs_verification自动判错。

## 验证与保留失败

- red.xml：7失败（6项新模块尚无实现、1项重复unknown被接受）；contract-red.xml：实现加载/回放后，仅2项精确复现重复误接受。
- green.xml：40通过；dev-before.json、dev-after.json、inspect.json及holdout-once.json保存原始口径。
- cli-red.xml：畸形外层JSON曾让CLI留空报告；补安全失败报告与不可覆盖验证。数组/null/深JSON三种都保存失败，不回显输入。
- verified.xml：54通过，包含13项真实PG感知回归，来源与CLI最终补丁前的版本；final-green.xml：44项最终离线验证，ruff通过。PG业务代码本包未改。
- source-red.xml：独立审查指出同文件不同索引跨split缺口，1失败/10通过；改整个文件SHA分组后通过。来源被改/非合成/目录逃逸/同family与同source越界均拒绝。
- 唯一PG在本包前后均34/100，P5-WP02=4/10，[账本快照](budget-after.json)。未读模型凭据、未发模型HTTP。

限制：小型本地合成合同集；文件摘要依赖可信本地manifest，不声称管理员不可篡改。没有统计显著提升、生产用户反馈、盲测模型性能或个人掌握结论。旧P2/P3/P4/P5失败和未知根因不删除。
