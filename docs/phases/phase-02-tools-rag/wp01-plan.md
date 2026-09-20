# P2-WP01 Implementation Plan

用户已于本任务确认继续实现。沿用同一目录及当前分支，不提交既有注释改动或.idea。

**Goal:** 两个受身份约束的只读合成事实查询，可从CLI执行并追溯来源，不改变P1任务状态。

**Architecture:** 独立事实核验入口先读已授权任务快照，固定调用人员资质与区域状态工具。工具参数只含业务引用；可信Identity独立传入。版本化本地JSON保存访问授权和事实，工具输出带查询时点、内容摘要和有效区间的证据。CLI不初始化模型客户端。

**Tech Stack:** 既有Python/Pydantic/asyncio/pytest；无新增依赖。

## 1. 工具契约与真实查询

文件：`src/anlan/tools/contracts.py`（参数/数据/结果DTO）、`src/anlan/tools/queries.py`（只读加载/授权/查询/超时）、`examples/synthetic/facts-v1/`（授权/人员/区域）、`tests/test_tools.py`。

- [x] 先写测试：实际修改临时合成记录会改变结果；来源版本/摘要可追溯；固定时钟下有效、缺失、过期、未生效、不适用分别表达。
- [x] 参数严校验，拒绝额外tenant/user和类型强转；授权清单按tenant/user/object读取，不同用户/租户拒绝且不读事实文件。
- [x] 异步reader由应用注入，整个授权+查询受wait_for超时；无重试，超时后不产生事实成功结果。读取/数据格式错误返回data_error，不返回底层异常文本。
- [x] `uv run --locked pytest -q tests/test_tools.py`，先红后绿。

结果合同：outcome=ok/unknown/error，reason细分missing/expired/not_yet_valid/not_applicable/invalid_parameters/access_denied/timeout/data_error；只有ok提供当前事实。有效区间统一为[start,end)，时间必须带时区；记录observed_at晚于查询时间不得作为当前事实。每份数据的对象+类型键唯一，避免任意选中冲突记录。

## 2. 独立核验与CLI

文件：`src/anlan/facts.py`、`src/anlan/cli.py`、`examples/synthetic/fact-refs.json`、`tests/test_facts.py`、`tests/test_facts_cli.py`。

- [x] 核验入口先调用service.get；从快照取task/correlation/revision/source_run，新建核验run_id；固定执行两个工具，分别保留失败，单个失败不吞掉另一个结果。
- [x] 复用JsonlTrace，记录工具名/结果原因/来源摘要/时间，不记业务事实正文；trace失败显式标记，材料checkpoint和history不变。
- [x] CLI增加check-facts --task --refs-file；在模型初始化前分流，使用独立--facts-dir（宿主配置）及--as-of（明确历史模拟时钟），默认真实UTC。入口不接收模型配置；合成延迟仅通过测试reader注入，不增加生产故障开关。
- [x] 先红后绿验证任务越权、引用注入、工具部分失败、模型初始化哨兵、真实PG跨进程和状态不变。

## 3. 演示、回归与交付

- [x] `scripts/smoke_facts.py`保存合成演示，包含成功、工具越权、超时注入及前后状态比较，结果标明真实查询与注入。
- [x] 启用项目PG环境跑全量pytest；跑P1冻结回归；ruff与diff检查；证据写入本包独立目录，不覆盖旧记录，不读取模型凭据。
- [x] 按requesting-code-review技能安排独立只读审查；处理实质性问题后进行相关验证。
- [x] 更新README、架构、status、roadmap、acceptance、能力矩阵、学习记录及wp01-handoff；WP02/RAG/平台追踪仍未实现，个人掌握不变。

不创建业务写工具、Graph新状态合同或数据库迁移。查询证据绑定源快照，核验期间材料可能更新；消费者必须比较revision，不能把旧证据宣称为最新任务结论。
