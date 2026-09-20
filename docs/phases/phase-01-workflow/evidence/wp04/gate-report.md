# P1 工程 Gate：通过（2026-09-20）

结论范围：材料分析/多轮补充、显式中断、可信入口模拟、持久化恢复、受限模型接入与基础评测链路。可以进入P2受控工具与知识阶段。**不代表模型泛化、生产安全、岗位匹配或本人掌握通过。** 用户已明确个人练习独立记录，不阻塞继续编码。

## 本次实际验证

| 证据层 | 实际命令 | 结果与入口 |
|---|---|---|
| 冻结工程回归 | `uv run python evals/phase_gate.py --output docs/phases/phase-01-workflow/evidence/wp04/frozen-regression-final.json` | 8/8案例、25步骤；[最终结果](frozen-regression-final.json) |
| 全量功能/真实PG | `uv run pytest -q --junitxml=docs/phases/phase-01-workflow/evidence/wp04/pytest-final.xml`，先启动项目PG并加载Env | 56 passed、0 skipped（含11项真实PG集成）；[最终XML](pytest-final.xml) |
| 跨进程完整演示 | `uv run python scripts/smoke_postgres.py --output docs/phases/phase-01-workflow/evidence/wp04/cli-smoke.json` | 9命令、3条提交记录，过期与越权按预期拒绝；[命令/SQL结果](cli-smoke.json)、[trace](cli-smoke.trace.jsonl) |
| 依赖与静态检查 | `uv sync --locked --link-mode copy`、`uv run ruff check .` | 锁文件同步与ruff均exit0 |
| 历史有限语义证据 | runner本地重新评分WP03归档结果 | 原3例相符，1条规则命中、1条模型命中；不是新模型实验，[原真实报告](../wp03/final-report.md) |

本轮新增真实模型请求0、token0、模型调用费用0。WP03的3次真实请求与1184 token仅作为历史来源保留，不重复计入本轮。实际供应商扣费仍未查询。

## 冻结口径

`phase01-regression-v1` 是新建、已见的合成工程回归，区别于materials-v1三个模型开发样本；案例和引用文件的规范JSON摘要固定于manifest。旧B3/旧holdout未迁移、未当未见测试。当前没有独立语义holdout结果，这项限制留在后续模型/检索质量评测中。

冻结案例覆盖完整输入、两轮补充、待补充时修正已填内容、输入错误、过期版本、身份隔离、幂等/冲突、明确的超时注入。执行真实Graph/服务，检查返回与保存状态一致。它衡量控制流合同，不衡量模型能否理解复杂制度或风险。

## 审查与失败留存

独立审查复现两个Gate执行器缺陷：返回值正确但checkpoint损坏仍可能假通过；Graph初始化异常可能中断整套并留下空报告。新增变异/初始化故障测试先失败，再修正；start/resume同时验证checkpoint，初始化失败保留逐例失败记录。6项runner回归及独立复核通过。

保留初版[回归结果](frozen-regression.json)、中间[复核结果](frozen-regression-reviewed.json)、初次[全量XML](pytest.xml)；最终Gate以上表final结果为准，未覆盖旧证据。原始模型传输/用量、开发集离线漏检、数据库未启动失败等历史结果仍保留在对应工作包。

## 阶段出口核对

- 工程：材料输入→追问→补充→更新→再分析→待人工复核可演示；重启与故障恢复、重复/过期/越权和丢锁保护有证据。
- 安全边界：模拟身份不是生产认证；规则/模型/人工复核区分；无批准字段、业务写工具或报警控制。
- 学习：本人已修改过追问并演示；核心状态/恢复/评测解释及独立修改排错仍待验证，记录未被勾成掌握。
- 文档：P1主计划已收拢为历史工作包索引；保留有实施价值的计划/ADR和原始结果，无需删除实验文件来“清洁”结果。阶段handoff和P2启动文件已准备。
- 后置风险：复杂语义/独立holdout、最终任务修订、取消、跨进程模型预算、生产认证、工具/RAG/Memory/多Agent/事件尚未实现或充分验证；不在本阶段出口中冒称完成。
