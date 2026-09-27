# 有限Judge校准 v1

冻结cases.json SHA256：003d77eb54083ba9f9980fae9e09c1fd5473b2e0668840cd55c58bc6f7eb49d4。两个证据包各三条，supported/unsupported/uncertain各两条。标签由AI按明确枚举事实构造，供人核对；不是独立人类金标或盲测。gold与标签来源只进入评分报告，不进入模型上下文；输入与评分标签分别保存。

观察为手写冻结SYNTHETIC夹具，不是本次真实工具查询。两任务同样的固定观察分别走单生成和双职责（独立风险生成+证据复核）；risk输入SHA必须相等。复核只产生另一份候选，不改写风险文本。固定双职责risk移除audit是离线消融，零额外请求；独立两路生成差异不构成复核改善生成的因果证据。

```powershell
python evals/evaluate_quality.py --mode scripted --output .runtime/judge-scripted.json
```

真实模式须已有明确实验授权、固定deepseek-flash进程凭据与唯一PG账本。P6-WP03独立文本实验最多8请求（2Judge+2×3单多），每模型实例1请求，无重试；旧P4-WP02与P3-WP03默认预算不变。P5感知问题仍归P5-WP02，不能借此包重置。

输出使用新路径，run IDs在调用前落盘。账本失败/未知照计，报告区分总用量与是否完整，外部并发请求另列。评分先通过引用/完整性合同；非法输出按全部相关标签invalid计入分母，不能删除差例美化准确率。小样本只作校准观察，不设置生产阈值或自动批准规则。
