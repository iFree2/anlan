# Quality corpus v1

2026-09-27冻结，manifest SHA256为e9af8164f039dedad8ada27b1a6aa56cf736cb96bc53e69724a87a7131004492。

11项：开发6项（旧两失败、新两真实成功、独立合成合同正常例和重复未知Badcase），合同留出5项。每来源文件SHA、索引、case/family/event身份冻结，同源记录与family不跨split。旧/新感知同样本全部在开发，不冒称留出。留出为AI事先构造并冻结的合同案例，标签可由显式枚举、输入/引用核对；不是独立人类金标、统计抽样或真实模型泛化集。首次回放后即已见。

合成数据和示例制度只用于本地实验。P5/P6反馈由synthetic_replay_actor产生；dev-duplicate是synthetic_dataset_annotation的离线争议标签，不写生产反馈表、不代表用户确认。needs_verification本身不是模型错误。旧模型输出缺失只可查状态，无法完整录制回放；不能用新输出补旧空缺。归因保留not_established，重复未知只能证明记录本身有重复。

在仓库根目录用`.venv/Scripts/python.exe -m anlan.interfaces.quality_cli`：

```powershell
# 元数据查看，不重新验证/调用模型。
python -m anlan.interfaces.quality_cli inspect --manifest evals/quality-v1/manifest.json --output .runtime/quality-inspect.json
# 只对记录里的候选重新运行当前验证器，不执行新工具或模型。
python -m anlan.interfaces.quality_cli replay --manifest evals/quality-v1/manifest.json --split dev --output .runtime/quality-dev.json
python -m anlan.interfaces.quality_cli replay --manifest evals/quality-v1/manifest.json --split holdout --output .runtime/quality-holdout.json
```

输出必须用新路径，不覆盖原始证据。接口没有live/retry选项，未提供通用任意代码回放。真正重新调用仅在明确实验下使用既有`evals/evaluate_perception.py --mode deepseek`，固定P5-WP02及唯一PG预占；当前4/10，没有因离线回放重新分配额度。inspect/replay无数据库和HTTP客户端，不读取凭据。

`matches_expected`包含不可回放状态符合预期的两例，`not_replayable`必须同时报告；不能将它们算作成功模型输出。WP02开发修复是拒绝重复unknown IDs，开发5/6→6/6标签匹配；模型成功率的改善仍只有WP01新2/2证据。
