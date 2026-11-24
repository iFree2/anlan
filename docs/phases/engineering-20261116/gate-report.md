# 四项演进协调门禁账本

日期：2026-11-16。本文件持续更新，只记录已经发生的证据。工程增量完成、模型质量、真实企业验证、个人掌握分别判断。

## A–E

| 门禁 | 状态与证据 |
|---|---|
| A 基线 | HEAD b8b80d4；无适用 AGENTS；读取状态/架构/P13 handoff/P9/P10/RAG草案；初始16条dirty路径hash与patch保存在ignored runtime。最小基线55 passed/5 skipped |
| B 蓝图 | 总蓝图的依赖图明确T1→M1→M2→M3、E1→K/E后续；三个窗口严格文件所有权，1/4串行 |
| C 详细设计 | 总蓝图及各增量详细设计，含合同/威胁/错误/审计/回滚/测试 |
| D 独立审查 | 首轮4项修订已实施；K2a两项、E2a三项、M2两项重要设计修订均已发送并落实后触发。问题与修复在包报告中 |
| E 可执行计划 | 总计划与独占包小计划；独立窗口thread IDs见handoff；所有窗口禁stage/commit、不得回退他人修改 |

## F/G 增量验证

| 增量 | 主窗口已经执行的结果 | 边界 |
|---|---|---|
| T1/M1/E1/K1 | `uv run --no-sync pytest -q tests/test_tool_registry.py tests/test_tool_executor.py tests/test_dynamic_mcp_contracts.py tests/test_enterprise_evaluation.py tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py` → 151 passed, 2.87s | 首轮完整新增集；不是整个阶段验收 |
| K2a | K1两文件＋`tests/test_knowledge_v2_parsing.py` → 130 passed, 1.70s | TXT bytes纯摄取，未发布；无真实多格式/持久化 |
| E2a | `tests/test_enterprise_evaluation.py tests/test_enterprise_evaluation_runner.py` → 63 passed,27.12s；实际CLI运行8场景，verify_run valid=true/errors=[] | 报告gate=blocked，工具注入故障保留，语义/人工与未刺激安全项pending，不是模型安全质量通过 |
| K3a | 协调4个retrieval测试文件88 passed,2.04s；独立复审88 passed+定向10 passed、限定Ruff通过，无剩余Critical/Important | 内存结构证据三API/BM25/RRF/向量排名替身；未验证真实embedding、持久化、原XLSX坐标真实性 |
| M2 | 协调真实PG registry/CLI/integration 18 passed,36.25s；独立catalog/runtime 61 passed,42.87s及Ruff；工具窗口含旧链198 passed,118.88s | 显式SQL022、独立管理身份、真实SDK发现与启停；生产动态业务调用待M3，不以发现冒充调用完成 |
| K3→E1 | 协调最终30 passed,18.33s（含随后3项来源身份加固）；独立复审时27 passed/限定Ruff，原三important重放7负例均正确拒绝或安全fail。实际CLI3场景pending/exit2，产物校验有效；窗口相邻267 passed | 真实TXT解析/检索与显式合成表IR筛选；语义/人工仍pending，无真实embedding或源XLSX解析宣称 |
| 原HTTP/CLI | 恢复PG后`tests/test_service_api.py tests/test_events_cli.py tests/test_perception_cli.py` → 6 passed, 36.52s | 本地合成，不是线上验证 |
| 原工具桥 | 工具子窗口完整定向118 passed,54.94s；包含真实Java HTTP/MCP SDK | 协调完整回归另行记录，不把固定MCP当动态运行时 |

首次协调新增集125 passed/4 failed，发生在K1原文件hash不足以绑定审核IR的实际RED期间；已增加IR内容摘要绑定，后续151项通过。失败不删除。

## 全回归及环境故障保留

1. 无显式测试DSN：760 passed/36 skipped/253 setup errors/2 failed。两失败也为CLI依赖DSN缺失；不是新增代码缺陷证据。
2. 找到桌面虚拟化PG17真实路径，普通LocalAppData仅残留不完整集群。仅启动既有完整本地集群；恢复后可连PostgreSQL17.11，未重建/清空数据库。pg_ctl曾因恢复超过30秒返回超时，服务随后完成恢复；以实际连接为准。
3. 带原开发库完整非live基线：1050 passed/1 failed/1 deselected/1第三方弃用警告，1476.33s。失败是`test_preflight_routes_are_authenticated_versioned_and_role_bound`退出清理临时qualifications.json遇Windows WinError32占用。未断言为已修复，相关21项独立重跑通过（17.11s）。
4. 新建独立`anlan_engineering_20261116`测试库，首次发现缺`public.vector`，停止本窗口该次不完整运行，保留log；只在独立库补齐现有vector扩展后重跑。未drop任何库，未改旧SQL/业务代码来掩盖环境问题。
5. 独立库完整非live回归完成：**1267 passed、1 deselected、1第三方弃用警告，884.45s，exit0**；JUnit为0 errors/0 failures/0 skipped。证据`.runtime/engineering-20261116/final-full-ready.log/xml`。该轮收集发生在M2/E2a实现前，后续新增与变更仍需复验，不据此提前标整个H通过。

6. 当前二轮Ruff检查发现37项错误，位于仍在实施的新增文件；已由对应所有权窗口继续处理，不把开发中检查当最终通过。

E2a协调原始产物位于ignored `.runtime/engineering-20261116/coordinator-evaluation/634cef62-c9f7-490a-af31-135f6601a383/`，另有子窗口版本化可再分发合成产物在evals/enterprise-eval-v2/runner-results。独立审查三项观测/评分/trace绑定缺口已通过篡改RED/GREEN关闭；协调实际重新校验保存产物通过。哈希完整性不等于对可信宿主恶意全量重签的认证。

本机复现环境（不要输出环境中的凭据）：

```powershell
. ./scripts/dev-postgres.ps1 -Action Env -PgBin 'C:/Users/msm84/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Anlan2Runtime/postgres-17.11/pgsql/bin'
$env:ANLAN_TEST_DATABASE_URL=$env:ANLAN_TEST_DATABASE_URL -replace '/anlan_dev$','/anlan_engineering_20261116'
$env:ANLAN_DATABASE_URL=$env:ANLAN_TEST_DATABASE_URL
uv run --no-sync pytest -q -m 'not live_model'
uv run --no-sync ruff check src tests scripts evals
```

## H/I 当前状态

2026-11-18本轮有限工程增量H/I通过，范围以acceptance.md为准，不代表四项全阶段完成或专家/本人掌握通过。

最终连续Gate：`uv run --no-sync python .runtime/engineering-20261116/run_continuous_gate.py`，内部为`pytest.main(['-q','-m','not live_model','--junitxml=.runtime/engineering-20261116/continuous-final.xml'])`。使用独立库anlan_engineering_gate_20261118及public.vector，实际 **1673 passed、1 deselected、1第三方警告，945.08秒，exit0**。JUnit0 failures/0 errors/0 skipped。新6项POSIX PID模拟加入此轮；Windows SDK文件30 passed，未宣称真正Ubuntu CI已运行。

此前整仓1666 passed/1 ConnectionTimeout失败、耗时79524.51秒保留；单条原事件测试耗时78492.736秒，系统同一长间隔附近有Kernel-Power休眠/恢复事件，具体全部因果未自动断定；不把该跨日时间作为性能指标。原事件模块定向20 passed/25.22秒。未更改连接超时或生产代码来抹除失败。

连续Gate仅为测试进程使用Windows临时ES_CONTINUOUS|ES_SYSTEM_REQUIRED请求防空闲休眠，结束finally清除，log确认released=True；未请求display/away模式，不改变电源计划。机制依据[Microsoft SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)，不阻止用户主动休眠。

最终`uv run --no-sync ruff check src tests scripts evals`为All checks passed；`git diff --check` exit0（保留Git行尾提示，不做全仓规范化）。309个源码/SQL/测试/依赖文件与运行前hash全部一致；16个原脏文件原内容保留，status仅追加。无stage/commit/分支切换、部署、真实模型实验或旧SQL修改。

wheel：9b8f72e5d26b58d3f40af1d797b8d455952fce728d2c655218a3d93c44b2d901；187个源码资源逐字节匹配。`scripts/verify_package_layout.py --wheel ... --output ...`完成离源码导入/23资源/9兼容CLI；新增管理CLI的wheel --help另行exit0。检查报告在ignored runtime，最终交接列关键入口与回滚。

字节敏感TXT夹具增加局部.gitattributes -text，`git check-attr`两路径确认text=unset，防止跨平台检出改写原字节/定位。未重写任何夹具或原用户文件。
