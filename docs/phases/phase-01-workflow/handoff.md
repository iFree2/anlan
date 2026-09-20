# P1 阶段交接：材料多轮工作流工程 Gate 已通过

结束日期：2026-09-20。依据 [Gate报告](evidence/wp04/gate-report.md)。工程通过与个人掌握分开：用户已要求优先持续开发、AI先跑通，个人练习后续补齐，不能把AI交付算作本人掌握。

## 目标与实际交付

产品始终是高风险作业全周期安全协同Agent，动火是首种完整支持方向；P1只完成材料准备入口，不代表完整产品。当前CLI实际执行LangGraph单工作流：四字段材料→规则缺项/可选模型语义候选→interrupt追问→用户局部补充→revision更新→再分析→待人工复核。无作业批准或安全结论。

模块与数据流：cli.py读取合成输入与本地模拟身份；service.py校验归属、版本和request_id，调用workflow.py；analyze与ask分开，避免resume重入导致重复上一次分析；model.py是有界DeepSeek适配器，analysis.py保留确定性规则。registry.py/postgres.py及sql/001_registry.sql保存归属、初始输入种子和提交回执；官方AsyncPostgresSaver保存当前图状态。trace.py记录必要关联/版本/用量，不记录凭据/隐藏思维链。

## 持久化与重要决定

内存demo退出即丢失任务；PG模式可跨进程续接。pending提交先持久化，Graph以sync durability保存节点，完成后写回执；这不是单一原子事务。recover根据run_id/revision/节点继续，避免重复合并。task锁与checkpoint共用连接，丢锁后旧执行不能经另一连接覆盖新状态。参见 [ADR001](../../decisions/001-workflow-state.md)、[ADR002](../../decisions/002-postgres-recovery.md)。

同request_id同载荷返回历史完成快照；同ID不同载荷或旧revision拒绝。已发生但未保存的模型调用仍可能在恢复时重复，不宣称exactly-once。thread_id不是权限，tenant/user须通过入口归属校验；CLI身份仅模拟，不能视为生产认证。

## 运行方法与环境

本地Python3.13.3；LangGraph1.2.11、checkpoint-postgres3.1.2、Pydantic2.13.5、psycopg3.3.6，完整依赖由uv.lock锁定。

```powershell
uv sync --locked --link-mode copy
uv run anlan demo
.\scripts\dev-postgres.ps1 -Action Start
uv run anlan db-init
uv run pytest -q
uv run python evals/phase_gate.py --output .runtime/p1-new-check.json
```

PG17.11独立实例127.0.0.1:55432；系统原PG10未改。数据库运行目录在LocalAppData/Anlan2Runtime/postgres-17.11，避免中文路径初始化问题；开发密码保存在忽略的.runtime配置中，脚本只加载Env不输出。新终端重新加载；停止仅用本项目脚本`-Action Stop`。安装/跨进程命令细节见README。

模型凭据由用户指定的`docs/DS.txt`提供，已Git忽略，不能复制/输出。P1只有WP03执行了3次真实请求，额度已用完；新实验另明确目的/样本/调用边界。P2首包合成只读工具不需要模型调用。

## 版本与验证证据

- 合同material-state-v1，数据库迁移001，Prompt materials-v1。
- 模型开发集materials-v1-dev-seen：3个已见合成案例；真实系统问题集合3/3相符，TP2包含规则/模型各1条，1184 token。记录请求别名deepseek-flash，未固定不可变供应商构建版本。复杂语义/泛化未验证。
- 新冻结集phase01-regression-v1：8个已见工程案例、25步骤检查。manifest使用规范JSON摘要，改期望需新版本；不是holdout或模型效果集。
- WP04最终56 tests passed（含11项真实PG），ruff通过；9命令完整PG演示、3条SQL提交记录；本包0新模型请求。
- [最终Gate与证据入口](evidence/wp04/gate-report.md)；历史失败/退化仍保留，归档预测重新评分不等于模型复跑或轨迹回放。

## 个人学习现状与未解决项

学习者有十年Java经验，Python可读但独立编写仍依赖AI；解释宜结合DTO、服务入口、事务/锁经验，仅补当前任务所需Python。本人已修改追问并提交演示，后续断言和主体代码由AI完成；TypedDict/Pydantic、Graph、状态合并、幂等恢复、评测归因等仍待本人讲解/修改证据。阶段要求见roadmap，具体记录见learning-log，不阻塞下一阶段编码。

尚未实现：真正的模型工具循环、RAG/pgvector、Langfuse、长期Memory、多Agent、结构化事件、FastAPI服务；最终任务修订/取消及生产身份也未完成。不能因P1Gate通过宣称以上能力。独立未见语义评测将在对应质量增量设计，不把旧已见holdout重新命名。

## P2 入口与不应重复的工作

读取 [P2 plan](../phase-02-tools-rag/plan.md) / [acceptance](../phase-02-tools-rag/acceptance.md)，优先建议P2-WP01：人员资质、区域状态两个真实执行的本地合成查询工具，带来源/时效/失败，身份从可信上下文注入，先固定路由，后接有界模型工具循环。

先冷启动Git/状态/最小smoke，确认首包范围再实现。不要重建Graph/PG恢复、不预建多Agent壳、不再为数据库基础设施扩功能、不整体复制旧项目。14个文件既有中文注释改动与.idea为用户工作区内容，保留；未知差异先按Git/测试核对。P2在同项目目录的新Codex任务中启动，模型GPT-6 Astra、high。
