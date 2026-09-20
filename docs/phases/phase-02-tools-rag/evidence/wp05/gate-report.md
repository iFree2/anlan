# P2工程Gate：通过（2026-09-21）

通过范围：受控合成事实工具、有界模型工具循环、示例知识/pgvector检索和引用、共享请求预算、本地来源追踪。可以进入P3 Memory与Context。**不代表模型泛化、全摘要主张充分引用、生产安全或本人掌握通过。**

## 最终证据

| 验证 | 结果 | 原始证据 |
|---|---|---|
| 全量功能与PG | 185 passed，0失败/错误/跳过，231.21秒；含26个真实PG场景 | [pytest-release.xml](pytest-release.xml) |
| 冻结P2工程回归 | 11/11，通过真实Graph、文件工具、本地编码、PG和Jaeger；模型明确为scripted替身 | [frozen-final.json](frozen-final.json) |
| 实际平台（python -O） | 正常与注入知识故障两条链，各6个span；父子/错误/来源/材料不变核对通过 | [observability-release.json](observability-release.json) |
| 旧真实记录只读导入 | 18事件成功，3条独立archived_import trace；API查到各6个span，没有执行模型或工具 | [archived-import.json](archived-import.json) |
| 本机平台部署 | 官方Jaeger2.21.0、固定SHA、4个回环TCP端口、无UDP；UI/API可用 | [jaeger-setup.json](jaeger-setup.json) |
| 静态/修复检查 | ruff通过；最终修复24项通过，包括优化模式、导出异常和部分导入报告 | [review-green.xml](review-green.xml) |

实际最终命令：加载项目PG Env；全量pytest时`ANLAN_OTLP_ENDPOINT`为空，网络替身与业务测试独立。另加载Jaeger Env后执行 `python -O scripts/smoke_observability.py` 与 `python -O evals/phase02_gate.py`，其完整参数/来源见同目录报告。`-O`下关键校验仍执行，不靠可删除的assert判定Gate。

Gate前后唯一生产账本均12次，新增预占0、历史记录未变；本包真实模型请求0。新授权余额88/100；P2-WP02和WP04各6/10，总已知19818token，P1历史三次/1184token单列。费用未查询，不能把本地模型计算或轨迹导入冒称新供应商实验。

## 审查、失败与口径修正

- 独立规格发现预算Gate只检查不超限，不能检测Gate中新增预占；已改为开始/结束快照和attempt_id集合比较，新增/删除均失败，实际新增数写入报告。保留[预算红测](gate-budget-red.xml)及修复结果。
- 独立质量复现关闭HTTP客户端使exporter抛RuntimeError、打断材料流程；现普通导出异常转trace_export_failed，本地JSONL和业务结果保留，BaseException继续传播。
- 将Gate编码器校验、平台smoke父子/来源/业务校验改为显式if/raise，优化模式不能删；[review-red.xml](review-red.xml)到[review-green.xml](review-green.xml)保留。
- 导入坏记录曾在已导出部分后丢掉报告；现保留成功/失败/未处理数及partial_failure，[import-partial-red.xml](import-partial-red.xml)保留。
- 初版冻结11/11虽通过，撤回场景会改变后续共享语料；改为独立临时文档，不修改冻结期望。保存初版、复核版和最终版，最终版含运行器摘要。
- 深层collector JSON在4KiB上限下的探索测试通过，并未复现新缺陷；对应XML如实保留为initial/runtime-limit，未冒称红测。

Jaeger启动路径曾出现Start-Process返回Path为空的竞态，已修复为核对实际路径和启动时间再写状态，两轮Stop/Start通过。批量状态篡改/端口冲突负测被自动审批拒绝，仅返回blocked by policy，未执行或重复该操作；采用普通生命周期与只读身份检查收束，不宣称这些负测通过。

## 阶段限制保留

真实效果证据是WP02和WP04各3个已见开发任务，均不是holdout。WP03混合检索没有命中收益；WP04有摘要次要主张未显式引用的Badcase。P2冻结集仅工程回归，不把这些结果换算为企业准确率、规模能力或个人掌握。

身份是本地模拟，Jaeger内存重启丢失展示数据；JSONL和PG分别承担证据/业务及预算持久化，不能互相冒充。PG曾未正常退出，原因未确定，恢复后通过不等于根因已修复。后续高影响动作仍由人工复核，本系统没有批准或实时控制接口。
