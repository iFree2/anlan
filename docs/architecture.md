# 架构：当前基线与已确定的演进边界

当前实际架构：Python CLI、Pydantic 边界校验、LangGraph 外层状态图，单分析节点。P1-WP01内存模式仅支持当前进程；P1-WP02接入官方 AsyncPostgresSaver、持久化归属/提交记录，支持跨进程读取、补充和恢复。P2-WP01新增独立只读事实核验入口。实现及验证状态以 [status](status.md) 为准。向量检索后续使用 pgvector；FastAPI、Langfuse、Compose 在相应业务增量引入，尚未安装或验证。

```mermaid
flowchart LR
    U[安全管理人员 / 合成申请] --> V[可信身份入口 + 输入校验]
    subgraph G[LangGraph 外层显式状态与条件边]
      V --> A[材料分析：规则 + 可选模型]
      A -->|缺项或歧义| Q[interrupt：补充问题]
      Q -->|Command resume| P[白名单字段合并 / 版本更新]
      P --> A
      A -->|无待补充项| H[待人工复核 / 标明分析能力与失败]
    end
    G --> C[checkpoint：可选内存或 PostgreSQL]
    G --> T[关联轨迹：task / run / correlation]
```

节点像 Java 的应用服务方法；TypedDict 描述图状态的形状，不负责运行时校验；Pydantic 类类似带 Bean Validation 的 DTO。节点返回部分状态更新，由 LangGraph 合并。材料始终只由经校验的用户输入更新；模型仅返回候选问题。`interrupt` 所在节点恢复时会从头执行，所以模型请求不放在该节点中。

模型失败不直接决定进入复核：代码保留规则缺项，有缺项仍进入 `waiting_input`，无缺项才进入 `awaiting_review`，同时保留 `semantic_status=failed`。依据 `workflow.py` 的规则合并与条件路由，以及冻结案例 `p1-08-model-timeout`；P2冷启动时修正了图中“或模型失败”的不准确简写。

首轮字段为位置、对象、方式、附件说明（沿用旧素材的字段名便于理解，判定规则是新版合成假设）。空字段由代码提问；模型识别明确歧义、缺细节、矛盾，必须返回字段内原文引用。引用存在只证明定位正确，不证明缺陷判断正确。模型无工具、无身份写入权、无批准字段。

身份与状态：tenant/user 是 CLI 本地测试入口注入的模拟可信身份，不来自材料或模型，尚不是生产鉴权。session 表示本次交互容器，task 是业务材料任务，thread 是 checkpoint 游标，run 表示一次提交执行；故障恢复沿用未完成提交的 run_id，correlation 串联任务。request_id 标识一次用户提交，重试保留；不能把框架 thread 当租户隔离机制。应用入口先检查归属再读写状态，PG 模式使用任务级锁与同连接写入阻止并发消费和丢锁后旧写。

### WP02 的持久化调用链

```mermaid
flowchart LR
  CLI[start / show / resume / recover] --> S[service：身份 / 版本 / 请求去重]
  S --> R[registry：任务归属 / 原始提交 / 返回快照]
  S --> G[Graph：当前状态与节点]
  R --> DB[(PostgreSQL anlan_v2)]
  G --> CP[官方 AsyncPostgresSaver]
  CP --> DB
  LOCK[同一连接：advisory lock + checkpoint 写入] -.-> R
  LOCK -.-> CP
```

`postgres.py` 在同一专用连接上组合 registry 与 saver，连接丢失即同时丢锁且无法写 checkpoint。初始创建先写归属，CLI 输出 task_id 回执后执行图。每次补充先持久化 operation，然后以 `durability="sync"` 写节点 checkpoint，最后保存完成回执；各次提交并非一个跨系统事务。故障留下 pending，recover 判断该 run 是否已合并输入，再继续未完成节点；已完成请求直接返回旧回执，用 show 取最新状态。分析完成但尚未进入 ask 的节点边界也需继续至 interrupt，不能仅凭 status 字符串认定可补充。

相关实现：`registry.py` 的合同/内存实现、`postgres.py` 的 SQL/官方 saver、`sql/001_registry.sql` 的任务/提交表及迁移版本、`service.py` 的幂等/恢复决策。图状态不接受模型写身份/批准。checkpoint 的受限反序列化不开放 pickle 回退。详细取舍见 [ADR002](decisions/002-postgres-recovery.md)。

部署实测使用独立 PG17.11（端口55432）。本机中文路径触发 PG 初始化编码失败，数据库运行文件放在用户 LocalAppData 的英文目录，源码不移动；脚本、位置和停止方法见 README。系统原 PG10 服务保持原样。记忆、生产认证、数据库备份和最终状态修改不在 WP02 范围。

## P2-WP01 当前事实核验

`check-facts`在模型初始化前分流：宿主Identity → `service.get`校验任务归属并取材料快照 → `FactReferences`校验独立对象引用 → 固定顺序两个工具 → 独立证据包/JSONL。`tools/queries.py`先按合成access清单检查tenant/user/object，再读取资质或区域记录；路径由宿主配置，业务ID不拼接文件路径。

参数、记录、结果由`tools/contracts.py`校验。单文件256KiB上限，带时区有效区间[start,end)，查询时点不能早于观察时点；同租户对象/资质类型键必须唯一。来源版本和原始字节摘要随证据返回；只有ok携带当前事实，unknown与error保留不同原因。工具默认2秒，无重试；异步超时加发布前单调时钟检查防止迟到成功。线程中的底层文件读取不能强制取消，但不发布迟到结果。

`facts.py`新建核验run，沿用task/correlation并记录源revision/source_run/material_status；不写入Graph、registry或operation。输出的awaiting_review只描述证据包，原材料状态不变。快照之后允许材料继续更新，消费者须比较源revision，不能把旧证据视为当前材料的最终结论。两个工具之一失败时仍保留另一个结果。JSONL记录工具名、原因、来源和时点，不保存事实正文；轨迹写入失败显示缺口。

该入口是代码固定路由；身份仍是本地模拟，合成文件不代表企业数据。WP02另提供以下模型循环，复用同一工具执行边界。

### P2-WP02 有界模型循环与预算

`check-facts-agent` → 已授权材料快照/引用 → 模型动作 → 白名单/严格参数/引用范围校验 → 只读工具 → 按call_id反馈观察 → 模型停止或代码预算截止。每次核验最多3回合/4动作/75秒；非法动作被拒绝并形成观察，最终摘要必须引用两个工具的观察但仍是未验证候选。

`model_gateway.py`在HTTP前调用`budget.py.reserve`并等待提交。SQL002新增项目级授权/尝试表，以授权行锁串行化计数与插入；成功、失败、未知预占都计数，无重置退款。`live.py`集中固定生产授权，P1材料模型入口也接入。超时、输出无效、用量未知与附加快照失败都有显式记录；隐藏推理不进入报告。决定与边界见[ADR003](decisions/003-model-budget-and-tool-loop.md)，原始小样本证据见[WP02交接](phases/phase-02-tools-rag/wp02-handoff.md)。

## 全周期数据流（已确定产品方向，尚未实现）

```mermaid
flowchart TD
    PRE[作业前材料 / 当前事实 / 知识] --> R[综合研判与人工复核]
    R --> CTX[带版本的作业上下文]
    E[可信接入：结构化视频与传感器事件] --> LINK[去重 / 时间窗口 / 作业关联]
    LINK --> ER[事件联合研判 / 人工确认与反馈]
    CTX --> ER
    ER -->|条件变化| PRE
    RAW[原始传感器 / 视频告警] --> SAFE[确定性阈值 / 紧急报警 / 联锁与实时控制]
    RAW --> E
    R --> DATA[轨迹 + 工具 + 检索 + 反馈 + 业务结果]
    ER --> DATA
    DATA --> BAD[Badcase / 失败归因 / 只读回放]
    BAD --> EXP[开发集改进 / 留出评测 / 版本对照]
    EXP --> ASSET[受控记忆 / Prompt / Skill / 工具与工作流资产]
    ASSET --> PRE
```

SAFE 不依赖 Agent 成功、响应或存在；Agent 无 SAFE 的写权限。原始事件不可被推断覆盖。视频事件契约包含 event_id、event_type、site_id、occurred_at、confidence、attributes、evidence_ref；传感器增加测点、读数、单位、阈值版本。可信接入绑定 tenant/site/event 身份；模型不能补造。乱序、重复、过期和错误关联要保留可查原因。

## 多 Agent 协作方向（P4 才实现）

```mermaid
flowchart TD
    LG[LangGraph：生命周期 / interrupt / 持久化 / 预算与取消] --> ROUTE[固定路由优先 / 可选受限协调 Agent]
    ROUTE --> K[知识研究 Agent]
    ROUTE --> F[事实核验 Agent]
    K --> JOIN[代码 fan-in：超时 / 部分失败 / 来源与版本检查]
    F --> JOIN
    JOIN --> R[风险研判 Agent]
    R --> C[证据复核 Agent]
    C --> HUMAN[安全管理人员复核]
    PER[感知事件研判 Agent：P5] -->|有效关联上下文| ROUTE
    LG -.->|父子预算 / deadline / 取消| JOIN
```

| 职责 | 最小上下文 | 工具权限 | 输出 / 不拥有的权力 |
|---|---|---|---|
| 协调 | 任务摘要、专业角色目录、剩余预算、执行状态 | 委派白名单 | 有界计划与执行状态；不能任意调用工具或写业务状态 |
| 知识研究 | 风险主题、租户过滤、有效时点 | 示例知识/案例检索、引用解析 | 带版本有效期证据；案例不等于当前事实 |
| 事实核验 | 对象引用、所需事实类别和时效 | 资质/设备/区域/天气/相邻作业只读查询 | 来源时间明确的事实或错误；不猜工具结果 |
| 风险研判 | 申请版本、事实、知识、只读规则结果 | 初版无工具，消费证据包 | 候选风险、未知、冲突和建议；不覆盖规则、不批准 |
| 证据复核 | 主张与引用映射、来源元数据 | 引用与有效性只读检查 | 支持性、冲突与缺证报告；不补造证据 |
| 感知事件研判 | 结构化事件、作业/区域/时间窗口 | 关联对象只读查询 | 保留 evidence_ref/confidence 的可用上下文；不关闭或降级告警 |

所有子任务传递 task_id/run_id/correlation_id、输入版本、deadline 和预算，独立上下文与白名单；身份另由执行上下文提供。Graph 节点校验子结果后才更新共享状态，不能让 Agent 直接写共享状态。两只读分支先并行；超时/部分失败返回显式未知，取消传递到子任务，重试不得突破父预算。冲突由来源与时效检查汇总给人，不以多数 Agent 同意替代证据。

演进顺序：单工作流 → 单 Agent 受控工具循环与综合研判基线 → 知识/事实两个专业 Agent 并行 → 风险/证据复核与受限协调 → 感知协作扩展。用同任务集比较成功率、调用正确率、引用支持、冲突发现、token/费用与延迟，再做去掉证据复核的消融；无收益的拆分允许退出主链。

## 官方接口依据

2026-09-17 核实：[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)（节点重入、checkpoint、Command resume），[官方包元数据](https://pypi.org/project/langgraph/)（Python ≥3.10），[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/) 与 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)（JSON 模式与非思考请求）。实际解析出的版本保存在根目录 uv.lock；联网和效果验证另记，文档兼容不替代运行验证。

## 历史资料来源与适用范围

旧仓库 `D:/src/agent学习/gpt下的安澜` 只读；本轮未复制原文数据或源码，未迁移任务清单/旧状态/旧架构。以下路径均相对旧仓库，链接指回原文件；这些链接失效不影响新仓库运行。

| 已读来源 | 2.0 提取的内容 | 明确不继承 |
|---|---|---|
| [用例](D:/src/agent学习/gpt下的安澜/docs/02-requirements/04-hot-work-use-cases.md) | 材料补充、事实查询、知识、辅助分析、人工复核、模型/工具故障场景 | 完整审批状态机、Java 唯一权威、旧 Phase 与签核 |
| [任务规格](D:/src/agent学习/gpt下的安澜/docs/02-requirements/06-agent-task-specification.md) | 输入/输出、来源/未知/冲突与评估问题 | 任务号作为节点、固定旧预算、Memory 默认禁用 |
| [B3 数据说明](D:/src/agent学习/gpt下的安澜/datasets/b3/application-completeness/v1/README.md)、同目录 manifest / inputs / gold / boundary-cases | 四字段问题形式、局部误报和类型/权限/输出边界思路；24 语义样本+12 边界样本 | 全部已见，只能做开发/回归参考；本包未迁移数据文件；以后迁移保留原件与来源，适配另版 |
| [旧报告](D:/src/agent学习/gpt下的安澜/evidence/b3-cloud-live/reports/20260916T141104448855Z-continuation/final-report.md) 与 [findings](D:/src/agent学习/gpt下的安澜/evidence/b3-cloud-live/reports/20260916T141104448855Z-continuation/agent-findings.md) | 结构有效与语义正确分离；额外字段误报、类别混淆、传输失败分开归因 | 53.3% precision 仅属旧四字段合成口径，不能沿用为新版基线；旧费用/批准非本项目无限授权 |

旧报告有 23/24 收到候选、23/23 结构有效、45 条建议中 24 命中/21 误报；20 个误报是额外字段缺陷，另 1 个是类别混淆。有效原文引用不保证主张得到支持。这些观察只指导本包保守 Prompt 与输出复验设计，尚未证明新版 Prompt 更好。旧 B4 设计/Prompt/数据本轮未读取，尤其未打开 holdout-gold；等真实优化问题出现再有选择参考。
