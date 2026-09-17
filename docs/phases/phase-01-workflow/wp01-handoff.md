# WP01 交接：离线工程部分交付，工作包待完成真实联调与学习验收

目标：LangGraph 材料分析→追问→用户补充→状态更新→再分析，CLI 看得见状态，支持后续专业 Agent 节点演进。本轮没有 PostgreSQL，也没有五个空壳 Agent。

已交付：单 Graph、四字段 Pydantic 合同、analyze/ask 两节点、InMemorySaver、身份归属入口、revision 检查、异步 DeepSeek 适配器（3尝试/20s/1024输出token/无重试）、规则降级与最小轨迹、开发评测及精简项目文档。代码由 AI 编写，本人能力尚未验证。

关键文件与调用链：`src/anlan/cli.py` → `service.py`（归属、版本、校验）→ `workflow.py`（状态/边/interrupt）→ `analysis.py` / `model.py`（规则、可选模型）；合同在 `contracts.py`；轨迹在 `trace.py`。起步阅读 contracts/workflow/service 三个文件。用户修改材料只走服务入口，模型只能给问题候选。

运行：按根 README 执行 `uv sync --locked --link-mode copy`，`uv run anlan demo` 或 `chat`；测试 `uv run pytest -q`。最近29 tests与ruff通过、demo三版本、三样本离线评测原始证据见 [verification](evidence/wp01/verification.md)。Prompt=materials-v1；数据=materials-v1-dev-seen；模型默认 deepseek-flash，**真实调用尚未验证**。所有历史 B3 数据已见，只供参考，未复制进仓库。

未完成与风险：

- 用户已选择复用 DeepSeek，尚缺配置文件完整路径。收到后只读加载到进程环境，勿复制凭据。建议用3个已见开发样本执行 `evals/evaluate.py --mode deepseek`，最多3请求，不另跑 demo 叠加请求；记录返回用量和失败，未知保持 null。评测输出不能覆盖旧结果。
- 本人练习待提交，入口 [learning-log](../../learning-log.md)。不能将AI实现、测试通过或文档阅读记作本人掌握。
- 内存 saver/归属索引退出即丢失；服务只支持单进程顺序调用；模拟身份不是生产鉴权。日志写失败会标 trace_warning 并保留流程，但不补造缺失轨迹。
- P1 Gate 未通过，不创建 P2 任务，不把本交接当阶段 handoff。

下一动作：按用户指示补真实联调/检查本人练习，然后 WP02 PostgreSQL 持久化。先冷启动检查 Git、status、此交接、[ADR001](../../decisions/001-workflow-state.md)，运行 demo；只规划归属索引与 checkpoint 持久化、重启及重复恢复保护。不要重建已验证工作流，不重读全部旧仓库，不提前做完整 RAG 或多 Agent。
