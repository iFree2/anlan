# 学习记录：白话版

这份文档不是“工程功能清单”，而是你以后复盘、面试和接管代码时要能说清楚的内容。

每个工作包都分开记录两件事：

- **工程事实**：代码和测试实际做到了什么，由 AI 实现也可以成为项目证据。
- **本人掌握**：你亲自操作、修改、排错或讲解后才能标为掌握。工程通过不等于你已经掌握。

下面按 P1 到 P8 排列。术语第一次出现会尽量换成日常说法；需要看原始证据时，点击对应阶段交接或学习单。当前工程状态见 [status](status.md)，完整能力地图见 [roadmap](roadmap.md)，重构后的代码位置见 [模块映射](refactoring/module-map.json)。

## 目录

- [P1：材料补充和工作流](#p1)
- [P2：查事实、查知识、调用工具](#p2)
- [P3：记忆和上下文](#p3)
- [P4：作业前多职责协作](#p4)
- [P5：感知事件和服务](#p5)
- [P6：质量和可靠性](#p6)
- [P7：接管和求职准备](#p7)
- [P8：操作台和云端部署](#p8)

<a id="p1"></a>

## P1：材料补充和工作流

这一阶段解决的问题是：安全管理人员拿到一份不完整的动火材料后，系统怎样追问、保存、恢复，并保证旧页面不会覆盖新内容。

### P1-WP01：材料多轮补充

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[materials.py](../src/anlan/workflows/materials.py)：`build_graph` 内的 `analyze`、`ask`：分析、暂停、合并补充字段。
- **从哪里调用**：[service.py](../src/anlan/workflows/service.py)：`WorkflowService` 调用 `build_graph`，`_execute` 用 `ainvoke` 启动或恢复流程。
- **看哪个测试**：[test_workflow.py](../tests/test_workflow.py)。

工程上已经实现了“材料分析 → 追问 → 用户补充 → 再分析”的最小流程。你曾亲自改过“作业方式”的追问文案，并跑过三轮演示；测试断言和核心实现由 AI 完成，所以个人掌握仍只记录为部分验证。

你应该理解：

1. `TypedDict` 是工作流内部状态的“字段说明书”；Pydantic 是入口和输出处真正执行校验的 DTO，接近 Java 的 Bean Validation。
2. 为什么“分析”和“等待用户回答”必须拆成两个节点：恢复时只重进等待节点，避免重复调用模型。
3. 用户只补一个字段时，系统怎样把它合并进原材料，而不丢掉其他字段。
4. “没有空字段”“模型返回 JSON 合法”“人工已经复核”分别只证明什么，不能混为作业安全或已批准。
5. `task`、`thread`、`run`、`tenant/user` 各自标识什么；知道 `thread_id` 为什么不代表有访问权。

可选练习：阅读 [材料工作流测试](../tests/test_workflow.py)，找到第一次仅补位置后仍保留对象和附件说明的断言，并用自己的话解释。

### P1-WP02：进程重启后的恢复

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[postgres.py](../src/anlan/infrastructure/postgres.py)：`PostgresRegistry`：任务归属、提交记录和数据库锁；[service.py](../src/anlan/workflows/service.py) 的 `_submit` 检查重复提交与旧版本。
- **从哪里调用**：[runtime.py](../src/anlan/interfaces/runtime.py)：`postgres_service` 装配数据库连接、记录存储和 checkpoint；[service.py](../src/anlan/workflows/service.py) 的 `recover` 执行恢复。
- **看哪个测试**：[test_postgres.py](../tests/test_postgres.py)。

工程上把工作流状态保存到 PostgreSQL，并保存任务归属和提交记录。这样进程重启后能恢复任务，同时避免重复提交和旧页面覆盖新内容。

你应该理解：

1. 只把 LangGraph checkpoint 保存到数据库，为什么还不够：还需要任务归属和提交记录。
2. `revision` 防旧回答覆盖新状态；`request_id` 防同一次网络请求重发。两者解决的问题不同。
3. 为什么锁、任务归属记录和 checkpoint 写入要使用同一数据库连接：避免旧进程丢锁后仍写回过期状态。
4. 模型请求已发出、结果尚未保存时，恢复为什么仍可能再次调用模型；这就是不能承诺 exactly-once 的原因。

可选练习：新建一条合成任务，补充一次材料后关闭终端；重新打开终端读回任务，再使用原来的 `request_id` 重发同一补充，观察版本和 run 是否重复变化。

### P1-WP03：真实模型最小联调

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[material.py](../src/anlan/llm/material.py)：`DeepSeekAnalyzer.analyze`：请求模型并检查返回；[material_analysis.py](../src/anlan/workflows/material_analysis.py) 的 `missing_issues` 负责空字段规则。
- **从哪里调用**：[materials.py](../src/anlan/workflows/materials.py)：`analyze` 节点调用 `analyzer.analyze`；[cli.py](../src/anlan/interfaces/cli.py) 负责选择离线或真实模型。
- **看哪个测试**：[test_model.py](../tests/test_model.py)。

工程上用三个已见合成样本做过三次真实模型请求，结构和当前标注相符，但这只能证明链路能通，不能证明模型具备泛化能力。

你应该理解：

1. 空字段由规则发现、语义歧义由模型发现，为什么必须分开记成绩。
2. “JSON 格式正确”和“模型判断正确”为什么是两件事。
3. 请求失败为什么仍要保留为失败样本；没有返回 token 用量时，为什么不能把它记成 0。

可选练习：阅读真实结果的第 003 例，指出原文、模型引用、问题类别和追问之间怎样对应；再说明第 002 例为什么主要是规则命中。

### P1-WP04：阶段工程验收

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[phase_gate.py](../evals/phase_gate.py)：阶段回归脚本：逐步执行材料路径并核对保存的状态。
- **从哪里调用**：[test_phase_gate.py](../tests/test_phase_gate.py)：测试调用验收脚本中的逻辑；[evaluate.py](../evals/evaluate.py) 是材料评测入口，与工作流回归分开。
- **看哪个测试**：[test_evaluation.py](../tests/test_evaluation.py)。

工程上冻结了工作流回归案例，验证补充、恢复、权限、版本和故障路径没有被后续修改破坏。这里的 Gate 指“这一阶段限定工程范围是否能交接”，不等于模型质量或个人能力验收。

你应该理解：

1. 工作流回归、旧模型结果重新评分、重新请求模型评测，为什么必须分开报告。
2. 为什么接口返回正确，还必须确认数据库 checkpoint 保存的状态也正确。
3. 冻结案例为什么可作为“防止旧问题复发”的回归集，却不能叫作真正没见过的 holdout。

可选练习：运行 `evals/phase_gate.py` 到一个新输出路径，查看过期版本提交被拒绝前后，哪些材料状态必须保持不变。

<a id="p2"></a>

## P2：查事实、查知识、调用工具

这一阶段解决的问题是：模型不能靠猜测说“某人有资质”或“区域安全”，必须查询当前事实和有版本的示例知识，并保留来源。

### P2 冷启动和首包范围

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[contracts.py](../src/anlan/tools/contracts.py)：查询参数、身份授权和工具结果的结构约定。
- **从哪里调用**：[facts.py](../src/anlan/workflows/facts.py)：`check_facts` 将可信身份传给事实工具。
- **看哪个测试**：[test_facts.py](../tests/test_facts.py)。

这里先明确后续工具的边界：人员/区域 ID 可以作为查询参数，但 tenant/user 必须来自可信入口，不能由材料或模型提供。

你应该理解：

1. 无记录、过期、不适用、查询超时，为什么要作为不同结果表达。
2. 当前事实为什么必须带来源版本、查询时点和材料版本，而不能偷偷改写材料状态。
3. 代码固定查询顺序和模型自主选择工具，各适合什么场景。

### P2-WP01：只读事实工具

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[queries.py](../src/anlan/tools/queries.py)：`FactTools.query_worker_qualification`、`query_area_status`：查人员和区域；`_query` 执行共同检查。
- **从哪里调用**：[facts.py](../src/anlan/workflows/facts.py)：`check_facts` 调用两个查询并整理证据。
- **看哪个测试**：[test_tools.py](../tests/test_tools.py)。

工程上实现了人员资质和区域状态两个合成数据查询工具。它们有身份、对象、时效和超时边界，只读，不批准作业。

你应该理解：

1. 为什么 `awaiting_review` 在事实证据包里只是“需要人工看”，不表示原材料已经补齐。
2. 为什么超时不能被解释成“资质不合格”。
3. 为什么工具返回的数据也要带来源和时点，而不是只回一句“通过/不通过”。

可选练习：复制一份合成事实数据，修改区域有效期，在同一个固定时点下比较查询结果；不要改归档数据。

### P2-WP02：模型调用受控工具

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[tool_loop.py](../src/anlan/workflows/tool_loop.py)：`check_facts_agent`：受控工具循环；[gateway.py](../src/anlan/llm/gateway.py) 的 `ModelGateway.call` 发请求；[budget.py](../src/anlan/infrastructure/budget.py) 的 `reserve` 预占额度。
- **从哪里调用**：[cli.py](../src/anlan/interfaces/cli.py)：调用 `check_facts_agent`，把身份、工具、模型和上限交给循环。
- **看哪个测试**：[test_tool_loop.py](../tests/test_tool_loop.py)。

工程上实现了模型提出工具动作、代码检查动作、执行只读工具、把结果交回模型、到达停止条件后结束的循环。同时使用项目级预算账本，避免重启进程就重置调用次数。

你应该理解：

1. 模型可以选工具，但白名单、参数校验、对象权限和最大步数分别由哪一层代码控制。
2. 为什么在 HTTP 请求发出前就要预占一次额度；进程崩溃后为什么不能假定“没扣费”而退款。
3. 为什么循环超时后仍要记录已经发出的请求和已获得的工具观察。
4. 三个任务运行成功、引用格式正确，为什么仍不能证明摘要的语义正确或模型对新任务可靠。

### P2-WP03：知识版本和检索

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[store.py](../src/anlan/knowledge/store.py)：`KnowledgeStore.ingest`、`withdraw`、`search`：摄取、撤回和过滤检索。
- **从哪里调用**：[tool.py](../src/anlan/knowledge/tool.py)：`query_knowledge` 调用知识存储；[evaluate_knowledge.py](../evals/evaluate_knowledge.py) 比较检索策略。
- **看哪个测试**：[test_knowledge.py](../tests/test_knowledge.py)。

工程上实现了版本化示例知识、撤回、权限、有效期过滤、本地中文向量和 pgvector 检索。混合检索在这批样本上没有收益，这个负结果已保留。

你应该理解：

1. 为什么 tenant/user、是否当前版本、是否撤回、是否过期、使用哪个编码器，都要在检索前筛掉不该看的文档。
2. 发布新版本、同版本偷偷改内容、撤回文档，分别该怎样处理。
3. 检索前几名都找对了，为什么最终回答仍可能没有依据。
4. 为什么“混合检索没收益”是有价值的结论，不能为了好看强行保留复杂策略。

### P2-WP04：三工具和引用摘要

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[tool_loop.py](../src/anlan/workflows/tool_loop.py)：`check_facts_agent` 组织人员、区域、知识观察；[tool_model.py](../src/anlan/llm/tool_model.py) 解析模型动作和最终回答。
- **从哪里调用**：[cli.py](../src/anlan/interfaces/cli.py)：工具循环入口；[evaluate_rag.py](../evals/evaluate_rag.py) 验证知识工具与回答引用。
- **看哪个测试**：[test_knowledge_tool_loop.py](../tests/test_knowledge_tool_loop.py)。

工程上把人员、区域、知识三个只读工具接到同一条受控链中，模型必须引用当次工具返回的原文。但发现了一个真实 Badcase：模型有额外主张没有明确引用对应依据。

你应该理解：

1. `knowledge_question` 是本次业务问题；tenant/user 是权限身份，为什么两者不能混在一起让模型决定。
2. quote 确实存在于原文，为什么仍不能证明整段摘要所有主张都有依据。
3. 知识工具故障时，为什么保留已有事实和“未知”，不能伪造向量结果或说“没有制度”。
4. 每个工作包有独立调用上限，为什么整个项目的累计上限不能重置。

### P2-WP05：追踪和阶段验收

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[trace.py](../src/anlan/infrastructure/trace.py)：`JsonlTrace.emit` 写运行记录；[telemetry.py](../src/anlan/infrastructure/telemetry.py) 转换并导出追踪数据。
- **从哪里调用**：[import_trace.py](../scripts/import_trace.py)：旧轨迹导入入口；[phase02_gate.py](../evals/phase02_gate.py) 运行阶段回归。
- **看哪个测试**：[test_telemetry.py](../tests/test_telemetry.py)。

工程上接入了本地 Jaeger/OTLP 追踪，并保留 JSONL、数据库状态和预算账本的不同职责。P2 工程通过不代表知识摘要质量或个人能力通过。

你应该理解：

1. JSONL、Jaeger、业务 checkpoint、模型预算账本为什么各有用途，不能互相替代。
2. 导入旧轨迹为什么要标成 `archived_import`，保留原来的时间和缺口，而不是装成新运行。
3. 为什么“模型走了几步”不等于“发了几次付费请求”。
4. 为什么关键校验不能只写 Python `assert`：优化模式可能删除它。

<a id="p3"></a>

## P3：Memory 与 Context

这一阶段解决的问题是：哪些信息可以跨会话保留、怎样过期和删除、模型本次到底能看到哪些内容。记忆只是辅助，不得替代当前事实。

### P3-WP01：偏好记忆的生命周期

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[store.py](../src/anlan/memory/store.py)：`MemoryStore.feedback`、`propose`、`change`、`list_active`：反馈、候选、修改及有效记忆读取。
- **从哪里调用**：[memory_cli.py](../src/anlan/interfaces/memory_cli.py)：`run` 根据命令调用记忆存储。
- **看哪个测试**：[test_memory.py](../tests/test_memory.py)。

工程上只实现了两类合成“呈现偏好”，例如希望内容简略还是详细；没有把资质、区域安全结论等当前业务事实写进记忆。

你应该理解：

1. 为什么用户偏好不能代替本次资质或区域查询。
2. 为什么反馈先是 candidate，必须确认后才变成可用记忆。
3. `expected_revision` 保护同一条记忆的并发修改；`source_version` 保护反馈来源版本，它们有什么不同。
4. 删除后为什么保存 tombstone（删除记录），防止旧请求把已删除记忆重新写回来。
5. 为什么过期记忆读取时过滤，比依赖后台定时删除更可靠。

### P3-WP02：上下文预算和筛选

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[assembly.py](../src/anlan/context/assembly.py)：`build_context`：按优先级装入本次模型可见信息。
- **从哪里调用**：[review.py](../src/anlan/workflows/review.py)：`synthesize` 调用 `build_context` 后才调用模型。
- **看哪个测试**：[test_context.py](../tests/test_context.py)。

工程上把材料、当前事实、未知项、知识、有效偏好按优先级组装到模型上下文，并用精确字节上限控制大小。

你应该理解：

1. 必需信息装不下时，为什么要拒绝请求，而不是悄悄删掉未知或错误信息。
2. 字节数和 token 数为什么不是同一个单位。
3. 用户偏好为什么只能调整详略和顺序，不能隐藏风险和未知。
4. 裁掉知识原文后，为什么仍要保留工具状态。
5. 业务指引或 Skill 为什么只能影响模型理解，不能授予工具权限。

### P3-WP03：单 Agent 综合基线和阶段验收

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[review.py](../src/anlan/workflows/review.py)：`collect_review` 采集证据，`synthesize` 组装上下文并生成候选。
- **从哪里调用**：[review_cli.py](../src/anlan/interfaces/review_cli.py)：调用采集和综合；[evaluate_review.py](../evals/evaluate_review.py) 比较记忆及知识策略。
- **看哪个测试**：[test_review.py](../tests/test_review.py)。

工程上把固定三工具采集、上下文组装和一次模型综合组合起来，并比较无记忆、有记忆、去知识原文三种策略。结果是：有记忆多花 token，但没有提高这批已见任务的接受率。

你应该理解：

1. 引用原文有效，为什么仍不能证明模型主张的含义正确。
2. 为什么一个正确的安全提醒，也可能因为没有符合合同的引用类型而被系统拒绝。
3. 模型填了 `presentation` 字段，为什么不等于实际输出真的满足详略和排序要求。
4. 去掉知识原文省 token，为什么不能自动称为质量优化。
5. 固定采集加单模型，与模型自己规划工具、多角色协作分别有什么区别。

<a id="p4"></a>

## P4：作业前多职责协作

这一阶段不是“多放几个模型就更聪明”，而是把确实需要分开的职责拆开，并用同一批数据比较成本、延迟和质量。

### P4-WP01：固定事实/知识分支

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[parallel.py](../src/anlan/workflows/parallel.py)：`collect_parallel`：并行采集、汇合、超时和取消。
- **从哪里调用**：[review_cli.py](../src/anlan/interfaces/review_cli.py)：选择并行采集；[multi_review_cli.py](../src/anlan/interfaces/multi_review_cli.py) 也调用该采集函数。
- **看哪个测试**：[test_parallel.py](../tests/test_parallel.py)。

工程上把事实和知识采集拆成固定并行分支，验证汇合、取消、超时和来源冲突。两例并行反而更慢，已保留。

你应该理解：

1. 代码固定的两个分支，为什么不能称为两个自主 Agent。
2. 为什么预算、材料版本、查询时点和身份必须由宿主确定，而不是交给子分支或模型。
3. 为什么取消、超时、来源冲突时要留下已成功的证据，但拒绝迟到结果。
4. 为什么结果相同或代码并行，不代表质量更高或更快。

### P4-WP02：风险候选和证据复核

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[multi_review.py](../src/anlan/workflows/multi_review.py)：`multi_review`：先风险候选、后证据复核；[evidence_review.py](../src/anlan/llm/evidence_review.py) 创建复核上下文并校验结果。
- **从哪里调用**：[multi_review_cli.py](../src/anlan/interfaces/multi_review_cli.py)：调用 `multi_review`；[evaluate_multi_review.py](../evals/evaluate_multi_review.py) 做单/双角色对照。
- **看哪个测试**：[test_multi_review.py](../tests/test_multi_review.py)。

工程上把“提出风险候选”和“检查候选是否有证据”拆成两个独立上下文，统一交给代码汇总。真实小样本中，双角色成本和延迟更高，复核也提出异议，不能称为质量提升。

你应该理解：

1. 模型复核、宿主合同校验、人工最终判断为什么是三层不同的事。
2. 同一供应商的两个模型调用即使上下文不同，为什么也不是独立专家投票。
3. 为什么一次调用已预占额度后，即使客户端异常也算消耗；父步骤数为什么不等于 HTTP 请求数。
4. 证据复核少看材料可以减少上下文，却会丢失哪些位置映射或注入说明。

### R1：职责分包

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[module-map.json](../docs/refactoring/module-map.json)：记录旧模块到当前职责包的位置映射；这部分是结构调整，没有新增业务流程。
- **从哪里调用**：[verify_package_layout.py](../scripts/verify_package_layout.py)：检查打包后的模块、资源和入口；[pyproject.toml](../pyproject.toml) 声明安装入口。
- **看哪个测试**：[test_package_layout.py](../tests/test_package_layout.py)。

工程上按职责把平铺模块整理成接口、流程、模型、知识、记忆、上下文、工具、基础设施等包，保留兼容入口和历史资源。

你应该理解：

1. 为什么数据库连接配置不应该顺带装配工作流。
2. 为什么“偏好有哪些合法取值”这种纯合同，不该为了读取它而依赖 PostgreSQL。
3. 为什么函数被旧模块重新导出后，旧的 monkeypatch 位置不一定还有效。
4. 为什么源码测试通过后，还要验证 wheel 包中的资源和 CLI。

### P4-WP03：Java API、MCP 和阶段验收

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[http_client.py](../src/anlan/tools/http_client.py)：HTTP 事实客户端；[mcp.py](../src/anlan/tools/mcp.py) 是 MCP 客户端适配；[AnlanFactApi.java](../integrations/java/AnlanFactApi.java) 是 Java 门面。
- **从哪里调用**：[smoke_business_bridge.py](../scripts/smoke_business_bridge.py)：启动并验证跨服务链路；[mcp_server.py](../src/anlan/interfaces/mcp_server.py) 是 MCP 服务入口。
- **看哪个测试**：[test_business_bridge.py](../tests/test_business_bridge.py)。

工程上让 Java 做窄 HTTP 门面和 MCP 适配，但 Python 仍是事实规则的唯一权威，避免建立两份业务规则。

你应该理解：

1. 为什么 Java 不能再建一套“谁有资质、区域是否可用”的第二事实库。
2. 为什么宿主传来的身份 header 仍要由服务端绑定和检查。
3. 为什么取消本地 await，不等于远端 HTTP/MCP 工具一定停止。
4. 为什么 HTTP 408、业务 unknown、网络失败必须分开表达。
5. 为什么工程 Gate 通过，不代表多 Agent 已经证明质量收益。

<a id="p5"></a>

## P5：感知协同和服务

这一阶段接入的是已经结构化的模拟事件，不做摄像机、IoT 平台或实时控制。原始报警始终独立保留，Agent 不得关闭、静音或降低它。

### P5-WP01：原始事件和可信关联

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[events.py](../src/anlan/infrastructure/events.py)：`EventStore.receive` 保存和去重；[events.py](../src/anlan/workflows/events.py) 执行事件准入与材料状态判断。
- **从哪里调用**：[event_runtime.py](../src/anlan/interfaces/event_runtime.py)：`process_event` 读取当前任务并执行关联；[events_cli.py](../src/anlan/interfaces/events_cli.py) 提供命令入口。
- **看哪个测试**：[test_events_postgres.py](../tests/test_events_postgres.py)。

工程上实现未戴安全帽、可燃气体异常两类合成事件的持久化、去重、乱序保护和任务关联。

你应该理解：

1. `event_id`、`sequence`、`observed_at`、`received_at`、材料 `revision/run` 分别解决什么问题。
2. 为什么先保存原始报警、后做任务关联；为什么关联写入、checkpoint 读取和锁要使用同一连接。
3. 为什么 `linked` 只表示当时关联成功；材料变了、事件过期或出现更新序号后，旧关联不能继续作为当前处置依据。
4. 为什么 `SourceBinding` 是可信宿主配置，而不是让事件正文或模型猜“属于哪个任务”。

### P5-WP02：修订材料、感知重核和失败保留

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[perception_runtime.py](../src/anlan/interfaces/perception_runtime.py)：`PerceptionRuntime.review`、`feedback`、`cancel`、`recover` 管理重核；[service.py](../src/anlan/workflows/service.py) 的 `revise` 创建材料新版本。
- **从哪里调用**：[perception_cli.py](../src/anlan/interfaces/perception_cli.py)：调用重核运行器；运行器再调用 [perception.py](../src/anlan/workflows/perception.py) 的 `synthesize_perception`。
- **看哪个测试**：[test_perception_postgres.py](../tests/test_perception_postgres.py)。

工程上让已完成的材料任务可以显式创建新版本，再针对事件发起独立重核和人工反馈。两次真实模型请求都被输出合同拒绝，0/2 接受，旧失败被保留。

你应该理解：

1. 已结束任务为什么要用 `revise` 创建新版本，而不能假装继续 `resume`。
2. 任务锁、重核运行锁、来源水位锁、反馈版本号分别防止哪类并发冲突。
3. 父流程被取消时，为什么仍要留下已拿到的部分观察；为什么最后发现材料变化也不能覆盖“已取消”的事实。
4. 真实模型 0/2 和“当时缺少字段级诊断”各说明什么；为什么不能不断重试到出现漂亮结果。

### P5-WP03：服务、SSE 和本机验收

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[api.py](../src/anlan/interfaces/api.py)：`create_app` 内的任务、事件、重核和反馈接口；[streams.py](../src/anlan/interfaces/streams.py) 提供 SSE 快照流。
- **从哪里调用**：[serve.py](../src/anlan/interfaces/serve.py)：`main` 启动服务；接口调用材料服务或感知运行器。
- **看哪个测试**：[test_service_api.py](../tests/test_service_api.py)。

工程上增加本地 FastAPI、身份配置、任务幂等、SSE 快照重连和持久重核取消。服务和干净 wheel 环境的验证通过；Docker/Compose 和远程 CI 没有实际运行，不能冒充已部署。

你应该理解：

1. `request_id` 和身份一起参与幂等判断，为什么不能只看一个随机 ID。
2. SSE 断开为什么只代表用户不再订阅，不等于业务任务自动取消。
3. 为什么重启后可以从持久快照继续读取，却不能假定正在进行的模型调用一定没有发生。
4. 为什么清洁环境脚本“显示成功”不够，还要防止清理异常被误报为通过。
5. 为什么服务接口测试通过，不能覆盖真实感知模型曾经 0/2 的质量失败。

<a id="p6"></a>

## P6：质量和可靠性

这一阶段把真实失败变成可复现案例，再做小范围修复和回归，不为了高分修改历史标签。

### P6-WP01：诊断感知模型输出并做最小复验

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[perception.py](../src/anlan/llm/perception.py)：`DeepSeekPerceptionModel.generate` 和 `safe_diagnostics`：生成结果并保留安全的字段诊断。
- **从哪里调用**：[perception.py](../src/anlan/workflows/perception.py)：`synthesize_perception` 调用模型并检查候选；[evaluate_perception.py](../evals/evaluate_perception.py) 是复验入口。
- **看哪个测试**：[test_perception_diagnostics.py](../tests/test_perception_diagnostics.py)。

工程上检查 Prompt、输出 Schema 和解析合同，补上安全字段级诊断。新增两次真实验证都通过，但旧的 0/2 失败仍保留；这不是泛化证明。

你应该理解：

1. 为什么先形成可证伪的故障假设，再发新的模型请求。
2. 为什么结构正确、有限语义检查通过，仍不等于真实现场模型已经可靠。
3. 为什么旧失败不能删除或用新成功覆盖。

### P6-WP02：反馈、坏例和回放

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[quality.py](../src/anlan/workflows/quality.py)：`load_corpus`、`inspect_records`、`replay_records`：读取、查看和使用旧结果回放。
- **从哪里调用**：[quality_cli.py](../src/anlan/interfaces/quality_cli.py)：`main` 分别调用查看或回放逻辑；不在此处重新请求模型。
- **看哪个测试**：[test_quality.py](../tests/test_quality.py)。

工程上把合成争议反馈变成 Badcase，复用录制输入做回放，修复后再跑回归。某些历史调用无法安全重放，也被明确保留。

你应该理解：

1. “查看旧轨迹”“使用旧结果重放”“重新调用模型”为什么是三件不同的事。
2. 为什么修复要在开发集和留出合同上分别检查。
3. 为什么不能为了把分数从 5/6 改成 6/6 而修改旧标签。

### P6-WP03：Judge 校准和单多角色复测

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[judge_calibration.py](../src/anlan/workflows/judge_calibration.py)：`calibration_context`、`score_calibration`、`ablate_audit`：组织校准输入、对照人工标签、移除复核作比较。
- **从哪里调用**：[evaluate_quality.py](../evals/evaluate_quality.py)：调用校准逻辑并执行单/双角色实验。
- **看哪个测试**：[test_judge_calibration.py](../tests/test_judge_calibration.py)。

工程上用少量人工标签检查 Judge 是否会误判，同时重测单模型和双角色链路。双角色没有显示出收益，成本和延迟更高；Judge 也有错例。

你应该理解：

1. Judge 为什么只能辅助人工评测，不能自己决定质量 Gate。
2. 为什么模型输出的“呈现字段”不等于文本真的按该方式呈现。
3. 为什么单/多角色在两例都成功，仍不足以证明多角色更好。

### P6-WP04：可靠性和阶段验收

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[benchmark_service.py](../scripts/benchmark_service.py)：`measure`、`run`：测并发请求、延迟和状态码。
- **从哪里调用**：[test_reliability_measurement.py](../tests/test_reliability_measurement.py)：验证测量逻辑；[test_service_reliability.py](../tests/test_service_reliability.py) 注入服务故障。
- **看哪个测试**：[test_service_reliability.py](../tests/test_service_reliability.py)。

工程上测量了同一任务并发读取、当前 wheel 和冻结回归。发现同任务并发会出现 409，保留为限制，不声称生产并发能力通过。

你应该理解：

1. 为什么测到 409 不是“系统没问题”，而是一个需要说明的可用性限制。
2. 为什么可靠性阶段的目标是量化、归因和保留限制，而不一定立刻引入队列或缓存。
3. 为什么工程 Gate 只能确认当前限定链路可复现，不能承诺生产 SLA。

<a id="p7"></a>

## P7：接管和求职准备

这一阶段把工程成果转成你可以演示、解释和如实写进求职材料的内容。

### P7-WP01：主链演示和排错资料

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[takeover_demo.py](../scripts/takeover_demo.py)：`run`、`execute`、`validate_step`：执行固定演示并逐步检查结果。
- **从哪里调用**：[takeover_demo.py](../scripts/takeover_demo.py)：`main` 是整条演示入口，内部运行已有脚本。
- **看哪个测试**：[test_takeover_demo.py](../tests/test_takeover_demo.py)。

工程上准备了固定、零模型调用的主链演示和故障资料。你需要做的是能独立运行它，并讲清一个失败如何定位。

你应该理解：

1. 演示为什么优先选固定、可复现的链路，而不是临时请求模型。
2. 工程证据和你的个人操作证据为什么要分开。

### P7-WP02：Memory 对比和小任务复用

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[evaluate_reuse.py](../evals/evaluate_reuse.py)：`transfer`、`evaluate`：把既有资产用于小任务并验证；Mem0 部分是静态分析，没有接入主链运行代码。
- **从哪里调用**：[evaluate_reuse.py](../evals/evaluate_reuse.py)：`main` 启动复用实验，复用现有记忆与综合逻辑。
- **看哪个测试**：[test_reuse.py](../tests/test_reuse.py)。

工程上阅读并比较 Mem0 的机制，没有直接把它装进主流程；同时用一个小型合成任务验证已有资产能否复用。

你应该理解：

1. “阅读或静态比较 Mem0”为什么不等于“已经接入并掌握 Mem0”。
2. 为什么小任务复用更能说明 Prompt、工具、流程和评测资产是否真的可复用。

### P7-WP03：有限图像和结构化事件对照

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[evaluate_multimodal.py](../evals/evaluate_multimodal.py)：`payload` 组织两类输入，`execute` 执行同案例对照，`parse` 校验结果。
- **从哪里调用**：[evaluate_multimodal.py](../evals/evaluate_multimodal.py)：`main` 选择实验模式；[make_multimodal_fixtures.py](../scripts/make_multimodal_fixtures.py) 创建合成图片。
- **看哪个测试**：[test_multimodal.py](../tests/test_multimodal.py)。

工程上比较结构化事件输入和两张合成图像的模型理解。两种方式在这批样本上没有质量增益。

你应该理解：

1. 为什么看过两张图片不等于完成视频监控能力。
2. 为什么没有质量收益也必须保留，而不是只展示“模型会看图”。

### P7-WP04：最终接管和如实表达

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[takeover_demo.py](../scripts/takeover_demo.py)：沿用已验证的主链演示；项目说明和求职材料属于文档成果，没有单独的运行模块。
- **从哪里调用**：[takeover_demo.py](../scripts/takeover_demo.py)：`main` 运行接管演示；个人修改或排错证据仍需你亲自完成。
- **看哪个测试**：[test_takeover_demo.py](../tests/test_takeover_demo.py)。

工程上准备了项目说明、架构讲解、简历草稿和最小个人证据清单。你还没有提交完整接管证据，因此不能把 AI 做的项目写成你独立上线的项目。

你应该理解：

1. 简历中怎样区分“我参与/我理解/我亲自完成”和“项目工程上已具备”。
2. 被问到失败实验时，怎样如实说清问题、证据和下一步，而不是掩盖失败。

<a id="p8"></a>

## P8：轻量操作台和云端部署

这是你在原半年计划之后追加的增量：让已有能力能被网页操作和云端演示，但不把它包装成生产系统。

### P8-WP01：可视化操作和版本边界

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[service.py](../src/anlan/interfaces/console/service.py)：`ConsoleService` 处理页面业务；[routes.py](../src/anlan/interfaces/console/routes.py) 的 `install_console` 注册接口。
- **从哪里调用**：[app.js](../src/anlan/interfaces/console/assets/app.js)：页面事件调用 [api.js](../src/anlan/interfaces/console/assets/api.js) 发请求，服务端接口再调用 `ConsoleService`。
- **看哪个测试**：[test_console.py](../tests/test_console.py)。

工程上加入网页操作台，演示材料补充、查询、事件、候选和反馈，并验证失败和恢复路径。页面使用替身模式，不等于页面已经验证真实模型效果。

你应该理解：

1. 页面提交的版本号为什么必须交给服务端检查。
2. 为什么网页“显示成功”仍要能追到任务、run 和持久化状态。
3. 为什么替身模式适合稳定演示，却不能替代模型效果评测。

### P8-WP02：云端部署和唯一预算

**代码导航**（当前分包后的路径；先看调用入口，再看实现，最后看测试）：

- **实现在哪里**：[service_models.py](../src/anlan/interfaces/service_models.py)：`ServiceModels` 装配模型；[budget.py](../src/anlan/infrastructure/budget.py) 管理唯一调用账本。
- **从哪里调用**：[api.py](../src/anlan/interfaces/api.py)：创建服务并调用模型装配；[verify_console_deployment.py](../scripts/verify_console_deployment.py) 验证部署后的访问与任务。
- **看哪个测试**：[test_console_live.py](../tests/test_console_live.py)。

工程上部署了独立的合成演示环境，浏览器、数据库查询和服务重启恢复均有记录；访问和预算边界仍被明确限制。

你应该理解：

1. 为什么云端演示环境不等于企业生产上线。
2. 为什么模型调用预算要有唯一账本，不能本地和云端各算各的。
3. 为什么访问 token、SSH 凭据、数据库管理权限必须分开，且不能写进仓库或日志。

## 当前本人实践结论

目前已确认的个人实践只有：你修改过一次作业方式追问，并运行了材料流程演示。其他工作包的代码、测试、实验和部署主要由 AI 完成；它们是项目工程证据，不自动变成你的个人掌握。

建议你从 P1 的五个问题开始，逐步完成“能解释 → 能改一处 → 能验证”的最小闭环。之后再按 P2、P3 的目录向后推进，不需要一次读完全部记录。
