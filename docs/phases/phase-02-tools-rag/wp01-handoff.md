# P2-WP01交接：两个受控只读事实工具

日期：2026-09-20。工程验收通过；P2阶段未结束，下一包自动推进有界模型工具循环。本人掌握仍待独立证据，按roadmap长期授权不以练习完成为编码前置。

## 已交付与运行

`query_worker_qualification`和`query_area_status`读取版本化SYNTHETIC JSON。参数只接受对象ID/所需资质类型，Identity从入口独立注入；授权文件按租户/用户/对象列出允许范围，无权时不读取事实文件。缺失、过期、未生效、不适用、参数错误、无权、超时、数据错误分别表达；只有ok带当前事实，并附资源、版本、SHA256、记录与有效区间。

独立`check-facts --task --refs-file`先校验任务归属，固定执行两工具；新的核验run关联原task/correlation/revision/source_run，不改变材料状态或提交历史。`--as-of`支持带时区的模拟时点，默认真实UTC；示例区域有效期仅至2026-09-21T00:00:00Z，此后真实时钟返回expired。完整命令见[README](../../../README.md#p2-wp01只读合成事实核验)。

模块：`tools/contracts.py`负责DTO，`tools/queries.py`负责授权/读取/时效/超时，`facts.py`负责固定核验与关联；`cli.py`在模型初始化前分流。无新依赖、数据库迁移或Graph合同变更，无模型凭据读取和真实请求。

## 验证与失败留存

| 证据 | 结果 |
|---|---|
| [最终pytest](evidence/wp01/pytest-final.xml) | 85 passed，0 failed/errors/skipped，含12项真实PG；114.09秒 |
| [真实CLI与故障演示](evidence/wp01/cli-smoke.json) / [轨迹](evidence/wp01/cli-smoke.trace.jsonl) | 5条独立进程命令，正常查询/跨租户拒绝；3个额外场景：明确标注超时注入、外国租户对象拒绝、缺失/过期；全部通过，材料与提交历史不变 |
| [P1冻结回归](evidence/wp01/p1-regression.json) | 8例25步通过，历史3例重新评分相符；不是模型复跑 |
| 静态与补丁 | `uv run --locked ruff check .`通过；Git diff检查通过 |
| [独立审查](evidence/wp01/review.md) | 发现并修复同步解析超时后可能发布成功结果；红测与修复后证据保留 |

最终全量命令：先加载`scripts/dev-postgres.ps1 -Action Env`，再执行`uv run --locked pytest -q --junitxml=docs/phases/phase-02-tools-rag/evidence/wp01/pytest-final.xml`。演示为`uv run --locked python scripts/smoke_facts.py --output docs/phases/phase-02-tools-rag/evidence/wp01/cli-smoke.json`。复现请换新输出路径，不覆盖证据。

初次全量[pytest.xml](evidence/wp01/pytest.xml)为83项通过，随后独立审查发现超时缺口，两个新增测试先失败：[deadline-red.xml](evidence/wp01/deadline-red.xml)。修复后工具/入口28项[通过](evidence/wp01/tools-reviewed.xml)，最终全量85项通过。不能仅凭初次83项通过否认缺陷；测试计数不代表模型效果或本人掌握。

## 限制与下一包

- 身份是本地模拟，具有文件/终端权限者能改授权配置；不是生产认证。只用合成数据，不给批准或合规结论。
- 证据绑定查询开始时的材料快照；消费者必须比较revision。证据包awaiting_review不改变原材料waiting_input。
- 单文件上限256KiB、默认2秒、无重试；wait_for加发布前截止检查拒绝迟到结果，不能强制终止底层只读线程。
- 当前是固定路由，模型尚不选择工具；RAG/pgvector/Langfuse/长期Memory/多Agent未实现。
- 本包新增真实请求0、token0。长期授权采用每包最多10次、新授权后累计100次保守上限，下一包先建立唯一跨任务预占账本，再做合成小样本真实工具循环；P1历史3次/1184token不并入新额度。
- 同目录原14文件中文注释与.idea保留；CLI自身功能改动与既有注释分开纳入版本。个人学习问题与可选练习见[learning-log](../../learning-log.md)，掌握状态未升级。
