# 材料分析开发样本 v1

来源：安澜 2.0 新编 SYNTHETIC 合成材料，非旧数据迁移。字段形式参考旧 B3（来源见 docs/architecture.md）；三个样本均为开发者已见，**不是 holdout**、不是企业标注或独立基准。expected 为单作者合成假设，尚无企业专家或独立标注者校准。

001：四字段在本轮最小范围已具体；不得额外要求时间/资质/气检等后续事实字段。
002：空位置只需一条 missing，其他字段不应连带误报。
003：“那里”缺明确指向，位置应 ambiguous；规则离线模式预期不能识别此语义。

评分匹配 (field, kind)，TP/FP/FN 保留，零分母 precision/recall 为 null。失败样本保留 FN，不过滤出成功请求后再宣称整体质量。exact_match 比较每例完整问题集合，另报告请求/语义状态。离线结果只解释基线能力边界；HTTP 替身结果不能作模型效果。

模型输入仅取 fields，不发送 expected。三个样本足够检查评分链路，远不足以估计泛化性能。本包不做 Prompt 优化或择优；后续在扩大开发集、冻结新版未见集后再做对照。每次输出文件拒绝覆盖，保留不改善/退化/失败。

```powershell
uv run python evals/evaluate.py --mode offline --output .runtime/eval-offline-v1.json
# 真实调用使用独立预算，需明确本次小样本约定；不要与 demo 累加后忽略请求总量
uv run python evals/evaluate.py --mode deepseek --output .runtime/eval-live-v1.json
```

此处离线与真实模式共用评分口径，但不同运行必须标明 mode，不得混为同一模型基线。
