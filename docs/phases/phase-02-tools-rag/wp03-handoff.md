# P2-WP03交接：版本化示例知识与真实向量检索

2026-09-20。工程包通过；这是摘录式知识证据，尚未把知识接入模型工具循环。下一包WP04做有界知识工具与引用摘要，随后WP05接追踪平台/P2 Gate。个人掌握仍待验，自动推进授权不变。

## 实际交付

- 专用PG17.11中安装pgvector0.8.6，明确为固定SHA256的社区Windows构建，不是官方二进制；44个安装文件可幂等校验，不覆盖冲突文件，不改系统PG10。
- FastEmbed0.8.0本地CPU BAAI/bge-small-zh-v1.5、512维；模型文件摘要固定到manifest，后续本地加载拒绝漂移。真实编码与unit-double-512测试替身明确分开。
- `knowledge.py`与SQL003保存文档/片段/版本/owner/读者/有效期/撤回及编码器ID；单文档原子摄取、同版本冲突拒绝、所有者修改、撤回后不可静默恢复。查询在排序前做tenant/user/current/withdrawn/time/model过滤。
- CLI `knowledge-ingest/query/withdraw`，向量检索与混合重排两策略；回答只取首条原文摘录，其余候选供复核。来源版本/内容摘要/有效期保留，知识文字不提供权限或执行指令。

## 验证

| 证据 | 结果 |
|---|---|
| [全量XML](evidence/wp03/pytest-initial.xml) | 151 passed，0失败/错误/跳过，70.29秒；含26个真实PG场景；之后知识状态文案补充，相关10项再次通过 |
| [真实CLI](evidence/wp03/cli-smoke.json) | 6命令，真实编码/PG，摄取/查询/撤回/跨租户/非所有者拒绝通过 |
| [真实检索对照](evidence/wp03/retrieval-report.md) | 8个已见问题，两策略各8查询；v1/v2与失败全部保留 |
| [PG扩展](evidence/wp03/pgvector-setup.json) / [模型](evidence/wp03/embedding-setup.json) | 安装摘要、版本、SQL距离0/1/2与真实512维编码可复核 |
| [P1冻结](evidence/wp03/p1-regression.json) | 8例25步通过，0新模型请求 |

独立规格/质量审查覆盖安装与知识主体：未发现确定的权限/事务/过滤缺陷；CLI知识错误文案已改为本地模型缓存检查。ruff通过。文档级gold仅适用于当前每篇一个chunk的语料，不能推广到多段文档。

## 实验结果与限制

首轮vector/hybrid均在7个有依据问题上recall@3=MRR=1，但把所有候选都拼作回答，支持比例宏平均仅0.4524。改为单主题首条摘录后，同一数据/语料/编码器得到支持7/7；混合检索无命中收益。收益来自回答选择，不能写成检索算法或泛化提升。1个无依据问题返回unknown；原文保真度v2分母仅7个有回答案例，旧版把空答案all([])记true的记录保留。

本包没有DeepSeek推理请求，累计仍6/100、P2-WP02为6/10；本地模型下载与计算不是供应商推理调用。费用未查询。

项目PG曾未正常退出，原因未确定；相关fixture失败及恢复后通过均保留。日志只支持发生过非正常关闭后恢复，安装脚本未启停服务；不得宣称已找到或修复根因。继续运行前先检查项目实例，PG测试skip不算通过。

## 复现

先`uv sync --locked --link-mode copy`、项目PG Start/Env，再`uv run python scripts/install_pgvector.py`，仅针对项目PG17.11。`uv run python scripts/smoke_knowledge.py --output .runtime/knowledge-demo-new.json`使用新合成租户；`uv run python evals/evaluate_knowledge.py --output .runtime/knowledge-eval-new.json`复跑真实本地检索，不消耗DeepSeek额度。输出路径必须新建，不覆盖证据。

批量CLI摄取按文档提交，非整批事务；显式撤回用单独命令。默认示例知识不是企业制度，摘录不保证回答复合问题。所有者和tenant来自本地模拟入口，不是生产认证；新的模型整合仍须保留这些边界。
