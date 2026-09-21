# 安澜 2.0

面向企业安全管理人员的高风险作业全周期安全协同 Agent。先深入动火作业，从准备与预审发展到依据/风险分析、作业中感知协同和事后质量闭环。所有演示均为 **SYNTHETIC 合成数据**，不是企业制度或合规依据；不自动批准，不控制或关闭报警。

P1—P3工程Gate已通过。当前支持材料多轮/PG恢复、事实与知识工具、用户偏好Memory、有界上下文与单模型综合候选。P3全量228测试通过，但真实消融仅接受6/9、有记忆未提高接受率；工程与模型质量分别报告。[P3交接](docs/phases/phase-03-memory-context/handoff.md)和[当前状态](docs/status.md)是继续入口。

## 启动（PowerShell）

前提：Python 3.13、uv；项目锁定版本见 `uv.lock`。以下内存演示无需数据库，持久化演示见下一节。

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

## PostgreSQL 跨进程演示（WP02）

当前 Windows 环境已准备独立 PostgreSQL 17.11，监听 `127.0.0.1:55432`，不改动系统原有 PG10 服务。在其他 Windows 环境首次运行以下安装命令会下载约380 MB的固定 EDB 官方 ZIP，校验本次已记录的 SHA256，再提取 server/bin/lib/share；来源是 [PostgreSQL 官网的 EDB ZIP 链接](https://www.postgresql.org/download/windows/)。

```powershell
uv run python scripts/install_postgres.py
.\scripts\dev-postgres.ps1 -Action Start
uv run anlan db-init
$task = (uv run anlan start | ConvertFrom-Json).task_id
uv run anlan show --task $task
uv run anlan resume --task $task --revision 1 --request-id location-1 --fields-file examples/synthetic/location.json
# 重复同一条命令：返回同一份 revision=2 结果，不重新分析
uv run anlan resume --task $task --revision 1 --request-id location-1 --fields-file examples/synthetic/location.json
uv run anlan resume --task $task --revision 2 --request-id method-1 --fields-file examples/synthetic/method.json
uv run anlan history --task $task
```

**每条 `uv run anlan` 命令都是一个新的 Python 进程。** `start` 在分析前向 stderr 输出 task_created 回执，最终 JSON 仍只写 stdout。若进程中途失败，保留回执中的 task_id，在新终端执行：

```powershell
.\scripts\dev-postgres.ps1 -Action Env
# 下方用你实际保存的 task_id 替换占位符
uv run anlan show --task <task_id>
uv run anlan recover --task <task_id>
```

正常等待补充时继续使用 `resume`；`recover` 只续接未完成提交，没有未完成提交时只返回当前状态。同 request_id 同载荷返回原快照，已有更新时该快照可能不是最新版本；用 show 查看最新状态。同 ID 不同载荷、过期 revision、其他 tenant/user 被拒绝。固定 ID 仅在同一 task 内去重；重复 start 会新建任务。

`start/show/resume/recover/history/db-init` 默认 PostgreSQL；`demo/chat` 默认内存，也支持 `--storage postgres`。`--tenant`/`--user` 仅为本地测试身份入口，拥有本机终端或数据库权限的人可自行设置，不能算生产认证。续接必须使用原来的 `--mode`；show/history 不调用模型。

数据库目录在 `%LOCALAPPDATA%\Anlan2Runtime\postgres-17.11\anlan2-data`，避免本机 PG 在中文路径初始化时的 UTF8 编码失败。随机开发密码在 Git 忽略的 `.runtime/postgres-dev/connection.json`，脚本只将 DSN 放进当前进程环境，不打印密码。也可自行设置 `ANLAN_DATABASE_URL` 指向专用开发库并运行 db-init（会建立 anlan_v2 schema）。本地脚本仅适配这一套开发实例，不作为多项目实例管理器。

```powershell
# 对真实本地 PostgreSQL 跑集成测试；未设置测试DSN时明确跳过，不能算通过
.\scripts\dev-postgres.ps1 -Action Env
uv run pytest -q
# 不再使用时停止本项目实例（保留数据，既有系统服务不受影响）
.\scripts\dev-postgres.ps1 -Action Stop
```

服务层保存归属和提交记录，Graph 保存当前状态，详见 [ADR002](docs/decisions/002-postgres-recovery.md)。两者不是单一事务；通过 pending 提交与 recover 协调。锁和 checkpoint 使用同一数据库连接，避免丢锁后旧执行写回。模型已请求但节点结果未保存时，恢复可能再次调用模型；本包不声称模型调用 exactly-once。

## P2-WP01：只读合成事实核验

人员资质、区域状态工具实际读取 `examples/synthetic/facts-v1/` 中的版本化JSON；`access.json` 是宿主提供的合成授权清单，不从业务参数读取身份。只核验当前任务快照引用，不改材料、revision或提交历史。

```powershell
.\scripts\dev-postgres.ps1 -Action Env
$task = (uv run anlan start | ConvertFrom-Json).task_id
uv run anlan check-facts --task $task --refs-file examples/synthetic/fact-refs.json --as-of 2026-09-20T12:00:00Z
uv run anlan show --task $task
uv run python scripts/smoke_facts.py --output .runtime/wp01-facts-demo.json
```

`--as-of` 明确标注为合成模拟时钟，省略时使用真实UTC；示例区域记录在2026-09-21T00:00:00Z后返回expired，这是预期行为。`--facts-dir`是宿主本地配置，不是模型参数；有本机文件/终端权限者能修改配置，因此这不是生产认证。查询路径不加载模型配置，即使指定`--mode deepseek`也不会调用模型。

引用输入只接受worker_id、qualification_type、area_id。结果分别给出ok/unknown/error，区分缺失、过期、未生效、不适用、非法参数、无权、超时和数据错误；失败不表示资质不合格。只有ok提供当前事实，来源包含资源名、版本、内容SHA256、记录ID、观察时间及[start,end)有效区间。

证据包有新的核验run_id，关联源材料revision/source_run_id和task/correlation；其中awaiting_review表示证据待人工复核，原材料仍可能waiting_input。查询过程中材料可被其他进程更新，使用证据前必须核对源revision。JSONL记录工具结果类别与来源，不含事实正文；日志失败显示trace_warning。来源单文件上限256KiB，查询默认2秒、无重试；超时丢弃迟到结果，不能保证强制终止底层只读文件线程。

演示脚本包含真实CLI/PG/文件查询、越权拒绝、无记录/过期，以及明确标记的延迟注入；不是模型效果实验。详细证据与限制见[P2-WP01交接](docs/phases/phase-02-tools-rag/wp01-handoff.md)。

## P2-WP02：模型工具循环与共享预算

```powershell
.\scripts\dev-postgres.ps1 -Action Env
uv run anlan db-init
$task = (uv run anlan start | ConvertFrom-Json).task_id
# 默认是明确标注的协议替身，不发模型请求
uv run anlan check-facts-agent --task $task --refs-file examples/synthetic/fact-refs.json --as-of 2026-09-20T12:00:00Z
uv run anlan budget-status
```

已有模型环境时添加`--mode deepseek`才发真实请求；每次核验最多3个模型回合/4次工具动作，循环最多75秒。工具选择由模型提出，权限、参数、业务对象范围和停止由代码决定。结果保留事实/未知与来源，最终摘要标记为未验证候选，不能自动批准或改材料状态。模拟时钟下的结果只用于合成演示。

生产累计账本在项目PG，固定授权ID `20260920-long-term-v1`。每次HTTP前提交预占，失败/硬退出/未知也占用，没有退款或CLI重置接口。`budget-status`不发请求；JSON证据里的预算快照只是档案，续接时以PG为准。本包已完成3任务/6次真实联调，查看[结果与限制](docs/phases/phase-02-tools-rag/evidence/wp02/live-report.md)无需重新调用。更多说明见[WP02交接](docs/phases/phase-02-tools-rag/wp02-handoff.md)。

WP04起，准备好同租户示例知识后，可给`check-facts-agent`加`--knowledge-question "动火现场如何安排监护？"`，启用第三只读知识工具。默认仍是明确替身，真实模式使用P2-WP04共享包额度。摘要需附本轮chunk与原文引用，错误保留其余事实；[真实实验](docs/phases/phase-02-tools-rag/evidence/wp04/live-report.md)中有一例额外主张缺少显式引用，不能将引用格式合法当成全摘要都有依据。

## P2-WP03：示例知识检索

```powershell
uv sync --locked --link-mode copy
.\scripts\dev-postgres.ps1 -Action Start
uv run python scripts/install_pgvector.py
uv run anlan knowledge-ingest
uv run anlan knowledge-withdraw --doc-id withdrawn-policy
uv run anlan knowledge-query --question "动火现场需要监护人员吗？" --as-of 2026-09-20T12:00:00Z
uv run anlan knowledge-query --question "人员资质要查当前记录吗？" --strategy hybrid --as-of 2026-09-20T12:00:00Z
```

安装脚本只支持本项目用户目录PG17.11，采用固定SHA256的**非官方社区pgvector Windows构建**，拒绝覆盖冲突，不改系统PG10。首次知识命令下载公共中文BGE小模型至.runtime，以后校验摘要并本地CPU推理；不需要模型密钥，不消耗DeepSeek请求。

示例文档来自`examples/synthetic/knowledge-v1/documents.json`，不是企业制度。摄取按文档原子提交；同版本不同内容拒绝，只有创建者能升版/撤回，已撤回文档不能靠重新摄取恢复。批量文件中的withdraw列表不自动执行，使用显式撤回命令；重复整个演示可用`scripts/smoke_knowledge.py --output <新路径>`，它使用新合成租户。

查询先筛租户/读者、当前版本、撤回、有效期和编码器，输出单主题首条原文摘录及其余候选、来源版本与摘要。它不是LLM生成回答，不保证覆盖复合问题；找不到当前可用依据时返回unknown，不等于没有制度要求。真实8题对照中混合检索无命中增益，默认仍为vector；初次低支持率与后续回答选择改动均保留，见[WP03交接](docs/phases/phase-02-tools-rag/wp03-handoff.md)。

## 可选真实模型

仅在进程环境中配置 `DEEPSEEK_API_KEY`，不要将密钥写进脚本、Git、日志或聊天。不自动扫描/加载旧仓库 `.env`，不使用其他开发工具的凭据。由用户指定的既有配置可只读加载到当前进程。

```powershell
# 已在当前进程环境安全设置 DEEPSEEK_API_KEY 后执行
uv run anlan demo --mode deepseek
```

固定官方端点、`deepseek-flash`、非思考模式；单个分析器生命周期最多 **3 次尝试**，每次输出上限1024 token、20秒超时、无自动重试。P2-WP02起真实入口还必须先加载项目PG环境，使用唯一共享预占账本：每包10次、新授权后累计100次保守上限，重启进程不会重置；失败和未完成预占也计数，用量未知记null。额度详情见[ADR003](docs/decisions/003-model-budget-and-tool-loop.md)。材料分析仅发送四字段合成材料和Prompt，不发送身份/凭据内容。

模型候选必须符合 Schema，字段和类别白名单、引用必须出自对应字段、同字段不可重复；失败保留确定性缺项并标 `failed`。这些校验不能证明语义正确。P2另有受控工具循环；示例知识已支持可选模型引用摘要，多Agent仍在后续阶段。

首次真实联调三次、无重试，返回输入1126/输出58 token；最终问题集合3/3符合当前已见开发标注，其中空字段来自规则、歧义来自模型。不是泛化准确率或生产验证；实际扣费未查询。查看结果直接读已保存报告，不必再次调用。各阶段需要掌握的内容已列入 [路线图](docs/roadmap.md)，AI先验证工程，个人掌握独立记录。

## 阅读与学习

推荐按调用链阅读：

1. [material_contracts.py](src/anlan/workflows/material_contracts.py)：Pydantic 材料 DTO；`QUESTIONS` 是练习入口。共享身份在 common/models.py。
2. [materials.py](src/anlan/workflows/materials.py)：状态、analyze/ask 节点、条件边及恢复；TypedDict 只描述形状。
3. [service.py](src/anlan/workflows/service.py)：模拟可信身份、任务归属、revision、幂等提交与恢复入口。

任务合同/内存实现位于 [registry.py](src/anlan/workflows/registry.py)，SQL持久化位于 [postgres.py](src/anlan/infrastructure/postgres.py)，同连接装配位于 [runtime.py](src/anlan/interfaces/runtime.py)，[迁移 SQL](src/anlan/sql/001_registry.sql)保持原位。现按 interfaces/workflows/llm/knowledge/memory/context/tools/infrastructure/common 分包；[目录与旧新映射](docs/refactoring/package-layout-report.md)。

随后看 [material.py](src/anlan/llm/material.py) 的请求与候选复验、[test_workflow.py](tests/test_workflow.py) 的行为断言。入口在 [cli.py](src/anlan/interfaces/cli.py)，旧 `python -m anlan.cli` 等命令保留薄转发。最小关联轨迹写入 `.runtime/traces.jsonl`，可通过 `--trace` 指定路径；不记原始字段、密钥、响应正文或隐藏思维链。

日志文件不可写时，输出 `trace_warning=trace_write_failed`，本地材料流程仍可继续；该次轨迹存在缺口，不会在事后伪造补齐。此策略适用于本地合成辅助演示，不代表未来高影响写操作可以绕过审计。

最小开发评测见 [样本与口径](evals/materials-v1/README.md)。三个已见样本用于打通预测、TP/FP/FN 与失败保留，不是留出集或充分的模型效果证据。

P1固定工程回归见 [冻结口径](evals/phase01-regression-v1/README.md)。以下命令运行8个已见工作流情境，并对历史模型结果重新评分；不会再次请求模型，输出文件不可覆盖：

```powershell
uv run python evals/phase_gate.py --output .runtime/p1-regression.json
```

它检查返回与保存状态、拒绝时状态不变和分析次数等，不代替真实模型质量评测。个人学习与阶段切换要求见 [P1阶段交接](docs/phases/phase-01-workflow/handoff.md)、[P2计划](docs/phases/phase-02-tools-rag/plan.md)。

## 本地追踪与P2工程验收

P2工程Gate已通过，历史185项测试、11场景冻结回归和实际平台查询通过；P3结束时重跑11/11仍通过，完整边界见[P2交接](docs/phases/phase-02-tools-rag/handoff.md)。个人掌握不随工程结果升级。

```powershell
# PowerShell 7；仅本项目目录内的官方Windows二进制
uv run python scripts/install_jaeger.py
.\scripts\dev-jaeger.ps1 -Action Start
.\scripts\dev-jaeger.ps1 -Action Env
.\scripts\dev-postgres.ps1 -Action Env
uv run anlan demo
uv run python evals/phase02_gate.py --output .runtime/p2-new-check.json
# 不使用时只停止本项目实例
.\scripts\dev-jaeger.ps1 -Action Stop
```

[Jaeger界面](http://127.0.0.1:16686)按run展示模型/工具子span，保留task/correlation和知识来源元数据；不导出材料、quote、密钥或隐藏推理。默认不启用网络导出，设置ANLAN_OTLP_ENDPOINT才发送到本地回环；失败显示trace_export_failed，本地JSONL与业务结果保留。模型step不等于付费请求，累计以`anlan budget-status`的PG账本为准。

平台内存重启会清空展示，JSONL仍保留。`scripts/import_trace.py --source <已有JSONL> --output <新报告>`仅生成独立archived_import轨迹，不调用模型/工具或恢复任务，不补造缺失耗时。服务列表使用2.21版本的`/api/v3/services`。

## Memory、Context与单Agent综合（P3）

```powershell
scripts/dev-postgres.ps1 -Action Env
uv run python -m anlan.memory_cli --help
uv run python -O scripts/smoke_memory.py --output .runtime/memory-new.json
uv run python -O evals/evaluate_review.py --mode scripted --output .runtime/review-new.json
uv run python -O evals/phase03_gate.py --output .runtime/p3-new-gate.json
```

输出路径须为新路径，保留历史证据。Memory来源/修正/确认均为显式命令，只接受合成详略与顺序偏好；删除保留tombstone，不能静默复活。综合入口为`uv run python -m anlan.review_cli --help`；同一应用用户的记忆和任务必须使用相同`--tenant/--user`。CLI仍是模拟身份，非生产认证。

复現事实/知识用明确as-of `2026-09-20T12:00:00Z`，Memory独立生命周期演示用9月21日至10月21日；真实时间的记录过期是预期。context预算以精确UTF-8字节计，实际token另记录；业务指引不授予权限。固定三工具采集＋一次综合与P2自主选工具循环不同。真实实验已占P3-WP03的9/10，不应直接重复完整9请求实验。

[真实消融报告](docs/phases/phase-03-memory-context/evidence/wp03/live-report.md)保留无收益、离题引用、错误上下文状态说明和材料说明无来源导致的拒绝；逐条引用存在不等于语义有支持。

## 受控事实/知识并行（P4-WP01）

`anlan.review_cli` 增加 `--collection serial|parallel`（默认baseline保留P3）。首包仅支持scripted综合，没有真实模型调用；固定双分支不等于多模型自治。来源、对象、时点、工具预算和材料版本由宿主校验，部分失败保留成功证据。

```powershell
scripts/dev-postgres.ps1 -Action Env
uv run python -O evals/evaluate_parallel.py --output .runtime/parallel-new.json
uv run python -O scripts/smoke_parallel.py --source .runtime/parallel-new.json --output .runtime/parallel-cli-new.json
```

输出使用新路径。[同集三路对照与失败记录](docs/phases/phase-04-multi-agent/evidence/wp01/verification.md)保留两例并行更慢的结果，不宣称延迟或质量收益。工具与Memory有共同deadline，材料收尾另有2秒；异步适配器须合作响应取消。

## 风险候选与证据复核（P4-WP02）

`uv run python -m anlan.multi_review_cli --help` 提供两模型职责入口；默认scripted，真实模式才走P4-WP02共享PG预占。两个角色独立上下文，协调器固定，不自动修订或批准。真实实验已占本包9/10，不重复完整9次实验。

`uv run python -O evals/evaluate_multi_review.py --source <已完成parallel报告> --output <新路径>` 可运行不付费替身对照；`scripts/smoke_parallel.py` 加 `--multi-review` 可验证跨进程入口。[真实报告](docs/phases/phase-04-multi-agent/evidence/wp02/live-report.md)保留复核作用、漏检与成本增加。

## 重要限制

- 内存模式退出即丢失任务；PostgreSQL 模式持久化归属/提交/checkpoint，JSONL 始终不是恢复数据源。
- 身份为本地模拟；已验证任务级并发互斥与丢锁拒写，不宣称生产权限、任意故障下 exactly-once 或生产 SLA。
- 已结束任务的重新修改、持久任务取消、业务写工具和企业事件接入尚未实现。P4增加只读采集/两角色模型的有界取消；Memory仅两类合成偏好，保留审计不代表生产隐私删除；引用摘要与综合候选仍有语义Badcase，不是生产合规结论。
- 功能测试和 HTTP 替身证明控制流/协议处理，不能证明真实模型质量；个人掌握见学习记录，默认待验证。

长期入口：[产品范围](docs/product-scope.md) · [架构与三张数据流图](docs/architecture.md) · [半年路线](docs/roadmap.md) · [能力矩阵](docs/capability-matrix.md) · [当前状态](docs/status.md) · [本人练习](docs/learning-log.md)。
