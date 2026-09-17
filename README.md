# 安澜 2.0

面向企业安全管理人员的高风险作业全周期安全协同 Agent。先深入动火作业，从准备与预审发展到依据/风险分析、作业中感知协同和事后质量闭环。所有演示均为 **SYNTHETIC 合成数据**，不是企业制度或合规依据；不自动批准，不控制或关闭报警。

当前是 P1 / WP01：CLI 单工作流，可观察“材料分析 → 追问 → 补充 → 更新状态 → 再分析”。外层使用真实 LangGraph `StateGraph`、条件边、`interrupt`/`Command(resume=...)`，不是手写对话循环冒充 Graph。默认离线规则仅识别空字段；DeepSeek 模式是独立、可选的真实 HTTP 调用适配器，联网验证状态见 [当前状态](docs/status.md)。

## 启动（PowerShell）

前提：Python 3.13、uv；项目锁定版本见 `uv.lock`。无需 Java、前端或数据库。

```powershell
Set-Location 'D:\src\agent学习\安澜2.0'
$env:PYTHONUTF8 = '1'
uv sync --locked --link-mode copy
uv run anlan demo
uv run anlan chat
uv run pytest -q
uv run ruff check .
```

`demo` 打印三行 JSON 状态快照：revision 1 缺位置/方式 → revision 2 仅缺方式 → revision 3 待人工复核。task/correlation 不变，run 每次改变。规则模式 `semantic_status=offline_not_checked`，不能证明歧义理解正确。

`chat` 首次回车使用演示材料；逐次输入以下局部补充即可：

```json
{"work_location_description":"SYNTHETIC：演示 A 区 1 号台"}
```

```json
{"work_method_description":"SYNTHETIC：电弧焊连接接缝"}
```

四个白名单字段为 `work_location_description`、`work_object_description`、`work_method_description`、`attachment_description`。补充只覆盖提交的字段，每字段最多 2000 字符。错误输入不消费模型请求，不修改已有状态；`/quit` 结束。最终 `awaiting_review` 仅表示本次辅助材料检查结束、需要人工复核。

## 可选真实模型

仅在进程环境中配置 `DEEPSEEK_API_KEY`，不要将密钥写进脚本、Git、日志或聊天。不自动扫描/加载旧仓库 `.env`，不使用其他开发工具的凭据。由用户指定的既有配置可只读加载到当前进程。

```powershell
# 已在当前进程环境安全设置 DEEPSEEK_API_KEY 后执行
uv run anlan demo --mode deepseek
```

固定官方端点、默认 `deepseek-flash`、非思考模式；单个分析器生命周期最多 **3 次尝试**，每次输出上限 1024 token、20 秒超时、无自动重试。三次上限不是账户预算或跨进程配额，重新启动会重置；不要通过反复启动绕过本轮小样本约定。失败尝试也计入预算，用量未知记 null。仅发送四字段合成材料和 Prompt，不发送身份/历史/凭据内容。

模型候选必须符合 Schema，字段和类别白名单、引用必须出自对应字段、同字段不可重复；失败保留确定性缺项并标 `failed`。这些校验不能证明语义正确。当前未实现工具循环、RAG 或五 Agent 协作。

## 阅读与学习

推荐按调用链阅读：

1. [contracts.py](src/anlan/contracts.py)：Pydantic 输入输出 DTO，像 Java Bean Validation；`QUESTIONS` 是本轮练习入口。
2. [workflow.py](src/anlan/workflow.py)：状态、analyze/ask 节点、条件边及恢复；TypedDict 只描述形状。
3. [service.py](src/anlan/service.py)：模拟可信身份、任务归属、revision 与生命周期入口。

随后看 [model.py](src/anlan/model.py) 的请求与候选复验、[test_workflow.py](tests/test_workflow.py) 的行为断言。入口在 [cli.py](src/anlan/cli.py)，最小关联轨迹写入 `.runtime/traces.jsonl`，可通过 `--trace` 指定其他路径。轨迹仅记来源标签、关联 ID、版本、问题字段、耗时与用量，不记原始字段、密钥、响应正文或隐藏思维链。

日志文件不可写时，输出 `trace_warning=trace_write_failed`，本地材料流程仍可继续；该次轨迹存在缺口，不会在事后伪造补齐。此策略适用于本地合成辅助演示，不代表未来高影响写操作可以绕过审计。

最小开发评测见 [样本与口径](evals/materials-v1/README.md)。三个已见样本用于打通预测、TP/FP/FN 与失败保留，不是留出集或充分的模型效果证据。

## 重要限制

- 当前 checkpoint、归属索引均在内存；退出进程即丢失任务，JSONL 不是恢复数据源。PostgreSQL 是下一工作包目标。
- 身份由 CLI 本地测试入口模拟，不是生产认证；仅支持单进程顺序调用，不宣称并发隔离或生产 SLA。
- 已结束的任务修改、取消/恢复、持久化幂等、工具、长期 Memory、企业事件接入尚未实现。
- 功能测试和 HTTP 替身证明控制流/协议处理，不能证明真实模型质量；个人掌握见学习记录，默认待验证。

长期入口：[产品范围](docs/product-scope.md) · [架构与三张数据流图](docs/architecture.md) · [半年路线](docs/roadmap.md) · [能力矩阵](docs/capability-matrix.md) · [当前状态](docs/status.md) · [本人练习](docs/learning-log.md)。
