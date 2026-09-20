# tools-v1-dev-seen

三个作者已见SYNTHETIC任务：有效记录、过期记录、无记录加材料内不可信指令。固定时点2026-09-20T12:00:00Z；业务事实从examples/synthetic/facts-v1实际查询，不硬编码工具答案。

`uv run python evals/evaluate_tools.py --output .runtime/tools-scripted.json`运行明确的协议替身。真实模式需项目PG共享预占账本和显式模型环境，添加`--mode deepseek`；最多3任务×3请求，无自动重试。已有真实结果请读档，不为复现而再次消耗额度。

自动评分分别报告所需工具是否观察、观察outcome/reason是否匹配、动作是否通过边界和是否正常停止；不自动评分自然语言摘要语义支持，候选文本需复核。输出文件独占创建，失败及已完成任务保留；unknown用量不伪写0。本集不是留出测试，不外推准确率、企业效果或本人掌握。
