# 本轮工程增量交接

2026-11-18。本轮A–I门禁完成，四项长期阶段没有因此全部完成。起始HEAD b8b80d4、原分支work/phase-01-wp-04保持；未stage/commit、未部署、未真实模型自测。

## 本轮结果

| 方向 | 实际交付 | 后续仍需验证/实现 |
|---|---|---|
| 工具体系 | 统一Registry/Policy/任务目录/模型绑定/Executor，人员/区域/知识迁移，check_facts_agent兼容与审计 | 新业务能力按合同继续注册，真实模型选择质量不由scripted证明 |
| 知识v2 | DocumentIR/当前独立ACL撤回/发布摘要，受限TXT原bytes解析，内存精确查找/BM25/RRF/向量协议，search/get_clause/query_table证据 | 真实多格式、授权语料、文控/持久化/索引发布/embedding重排与生产检索质量 |
| 安全评测v2 | 统一清单与独立安全门禁，原生8场景和知识3场景，观测→重评分→trace/版本可核验 | 60—100条审核数据、真人金标/逐主张语义、未见留出、Judge校准/真实模型对照 |
| 动态MCP | 独立管理员CLI、PG注册版本/启停/刷新、真实SDK生命周期，设备3能力经同一本地执行边界及SQL023审计 | 人员/票据端到端、双源时间分工/分页、普通对话/操作台装配、真实企业/TLS/IAM |

设备实际链：可信Identity与任务读取 → 可信厂区/对象授权及唯一来源 → 冻结catalog/lease → 模型动作 → 本地Registry/Policy/Executor → SDK call_tool → M1请求/来源/完整性绑定 → PG当前代次与共享锁审计发布 → 观察/unknown/partial/unusable与候选。模型不能提供身份或任意URL/命令，管理入口不提供绕过执行器的call。

## 最终证据

- 连续整仓：**1673 passed、0 failures、0 errors、0 skipped；1 live_model排除、1第三方弃用警告，945.08秒，exit0**。原始log/JUnit在`.runtime/engineering-20261116/continuous-final.*`。
- 最终Ruff All checks passed；git diff --check exit0。309个源码/SQL/测试/依赖文件运行前后hash一致，16个原dirty文件原文保留。status等总文档仅追加，不升级本人掌握。
- wheel SHA256 `9b8f72e5d26b58d3f40af1d797b8d455952fce728d2c655218a3d93c44b2d901`；187源码资源逐字节匹配、154模块离源码导入、23资源、9兼容命令和新增MCP CLI help通过。wheel在`.runtime/engineering-20261116/final-dist/`。
- 设备首包串行定向277 passed，M2定向198 passed，知识v2定向218 passed。独立审查的可用性/伪引用/同步截止、撤权元数据、Schema引用资源、注册并发等Important均有RED/GREEN关闭。
- E2八场景报告blocked（故障保留）；知识三场景报告pending（语义/人工未验）。它们不是Agent模型安全质量已经通过，不能把工程测试总数当质量指标。
- 原整仓1666 passed/1 PG连接超时及跨日异常耗时、定向20 passed保留；更早基线错误/跳过、冷启动失败不删除。连续复验使用临时进程防空闲休眠，finally清除且log确认released=True，未修改电源计划。

可复现核心命令（先显式隔离测试DSN与public.vector，凭据不打印）：

```powershell
uv run --no-sync pytest -q -m 'not live_model'
uv run --no-sync ruff check src tests scripts evals
uv build --wheel --offline --out-dir <new-output-directory>
uv run --no-sync python scripts/verify_package_layout.py --wheel <wheel> --output <new-report.json>
```

本机最后连续命令为`uv run --no-sync python .runtime/engineering-20261116/run_continuous_gate.py`，内部调用上述pytest参数并输出JUnit；纯测试PID helper已补Windows/POSIX分支，6项POSIX模拟及Windows SDK文件30项通过，实际Ubuntu CI仍未运行。局部.gitattributes固定逐字节TXT夹具，未重写数据。

## 文件入口与审查

- 总蓝图/依赖/门禁：`docs/superpowers/specs/2026-11-16-engineering-evolution-design.md`、对应总计划。
- 完整命令/失败与Gate：`docs/phases/engineering-20261116/gate-report.md`、`acceptance.md`及各包report。
- 企业MCP接入：`docs/integrations/dynamic-mcp.md`；公开语料候选：`public-corpus-sources.md`。
- 核心代码：`tools/registry.py`、`policy.py`、`executor.py`、`builtin.py`、`workflows/tool_loop.py`。
- 新知识：`knowledge/documents/`、`governance/`、`parsing/`、`retrieval/`。
- 动态能力：`tools/dynamic_mcp/{catalog,registry,runtime,routing,execution}.py`、`workflows/external_inquiry.py`、`llm/dynamic_tool_model.py`、管理CLI与新增SQL022/023。
- 评测：`evaluation/`、`evals/evaluate_enterprise.py`、`evaluate_knowledge_v2.py`与enterprise-eval-v2目录。旧数据/报告不改写。

## 回滚及边界

没有云端发布需要回滚。先停用本轮inquiry装配/显式disable相关服务并关闭会话，再人工撤自有新增文件/原文件中的自有hunk；新文件清单与hash在`owned-files.json`，撤销前确认没有后续用户编辑。不得整体reset/clean/restore、整体stage或覆盖原status/roadmap草稿。

已应用SQL022/023的不可变注册/调用审计默认保留，不DROP、降generation或恢复旧已撤权目录。旧SQL、预算/令牌未修改；隔离测试库保留，系统PG10/云端未操作。本地PG17使用既有完整集群，源码中的主initializer不自动授权注册管理。

冷启动可能触发工作deadline并返回缺证；取消后有独立清理窗口，不能承诺总墙钟严格等于5/60秒。stdio只运行受信程序，不是任意代码沙箱；生产TLS/企业系统、真实模型效果和正式法规适用性待验。表格地址来自合成审核IR推导，未认证原XLSX。

## 下一轮依赖

先取得许可可追溯的真实小样本和人工审核，推进真实解析/治理持久化，再以统一报告做检索对照；MCP按同一底座推进人员与票据/分页来源策略，最后另审普通对话入口装配与真实模型有限实验。公开数据可候选取用，不等于当前企业事实，也不等于未见金标。本人仍需亲自解释/修改/验证，AI交付不能自动标记掌握。

## 2026-11-22 ECS 发布续记

AGENTS.md新增自动发布约定后，本轮已发布到`/opt/anlan2/releases/engineering-20261119`。应用提交57c7c8b、发布提交9014962、wheel SHA9b8f72e5…、数据库备份SHA0e7acd8b…；服务PID4107178。发布前后全部表数量/逐行摘要、ledger/packages/statuses、配置/环境/systemd、角色及迁移保持，模型尝试146不变、六类pending为0。SQL022/023未应用、MCP未注册/启用，本批0模型请求、零业务写入验收。详见[发布记录](../deployments/2026-11-22-engineering.md)。

发布不改变“下一轮依赖”：线上只安装工程模块和旧功能兼容版本，不代表动态设备入口已接普通对话、企业MCP已接入、真实文档或模型质量已通过。
