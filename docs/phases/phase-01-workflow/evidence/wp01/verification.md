# WP01 验证记录（2026-09-17—18）

环境：Windows / Python 3.13.3，LangGraph 1.2.11，checkpoint 4.2.0，Pydantic 2.13.5，HTTPX 0.28.1，pytest 9.1.1。完整依赖与包哈希在根目录 uv.lock。未安装 PostgreSQL/FastAPI/Langfuse/pgvector；安装过程的跨磁盘 hardlink 提示通过 `--link-mode copy` 避免，无功能影响。

| 实际命令 | 结论 | 原始证据 |
|---|---|---|
| `uv sync --locked --link-mode copy` | exit 0，本机锁文件可安装 | [commands.json](commands.json) |
| `uv run pytest -q --junitxml=docs/phases/phase-01-workflow/evidence/wp01/pytest.xml` | 29 passed，exit 0 | [pytest.xml](pytest.xml) |
| `uv run ruff check .` | All checks passed，exit 0 | [commands.json](commands.json) |
| `uv run anlan demo --trace docs/phases/phase-01-workflow/evidence/wp01/demo.trace.jsonl` | 版本 1→2→3，最后待人工复核，离线语义未核查 | [commands.json](commands.json)、[demo trace](demo.trace.jsonl) |
| `uv run python evals/evaluate.py --mode offline --output docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json` | 三个样本均保留；001/002 exact match，003 ambiguous 漏检 | [结果](eval-offline-v1.json)、[trace](eval-offline-v1.trace.jsonl) |

工作流验证覆盖局部合并、二次追问、未改字段保留、输入拒绝不改状态、版本检查、会话独立、跨租户/用户拒绝、模型失败保留规则、重入不重复上一个分析节点、日志失败可继续。HTTP MockTransport 覆盖请求协议、无效/截断/空输出、伪引用、重复字段、额外批准字段、超时、429、连接失败及3次上限实现中的单次上限测试。输入注入测试只证明现有代码权限边界，不宣称已测真实 LLM 的抗注入效果。

开发评测原始记录含 TP/FP/FN 与每例输出：总 TP=1、FP=0、FN=1，完整问题集合相符 2/3。这是**离线规则能力边界**，不是模型准确率。所有样本已见；标签为单作者合成假设，不是企业安全标准，未冻结独立留出集。

真实模型请求：**0**；未提供既有配置的完整路径，未读取密钥；本轮真实 token/调用费用为0（无调用）。适配器测试使用合成 HTTP 响应，不能证明网络/账户/供应商能力，更不能证明模型效果。

独立代码审查发现并复现了日志异常卡住任务、失败丢模型/Prompt 版本、计划中的身份状态表述偏差。先运行回归得到5项失败，再修复；复核原问题已覆盖。早期新测试先因未实现模块报错，再实现；没有用通过数量推断掌握或模型质量。

未验证：进程重启恢复、并发写同任务、生产认证、工具失败/真实工具链、Memory 冲突、RAG/多 Agent/事件/SSE、真实模型与本人练习。这些按路线分阶段实现，并非本轮全套准入项。
