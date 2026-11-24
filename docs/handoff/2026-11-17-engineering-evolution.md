# 四项工程演进续接账本（进行中）

开始2026-11-16，续作2026-11-17。本文件不是最终验收签字。用户多次明确继续，授权独立窗口按边界推进；无须重新请求普通实现批准。

## 入口

- 总蓝图：`docs/superpowers/specs/2026-11-16-engineering-evolution-design.md`
- 总计划：`docs/superpowers/plans/2026-11-16-engineering-evolution.md`
- 门禁与真实失败：`docs/phases/engineering-20261116/gate-report.md`
- 初始保护清单/patch：ignored `.runtime/engineering-20261116/`。16个原脏文件原文均保留，status只追加说明；不stage/commit/reset/clean，不切分支。

## 所有权和窗口

| 窗口 | ID | 当前责任 |
|---|---|---|
| 工具/MCP | 01a1e4dd-1146-7fc0-aafe-36737ee08426 | T1/M1已交付；M2注册/SDK生命周期实施审查，之后才M3动态调用设计 |
| 知识 | 01a1e4dd-21e8-7f42-ad3b-ac4784df432c | K1/K2a已交付；K3a结构证据检索收口，所有权knowledge新子包 |
| 评测 | 01a1e4dd-1912-79d1-911a-31036991bb8d | E1/E2a已交付；正在设计K3真实检索→E1统一报告增量（仅设计） |

主窗口负责跨包设计审查、协调复验、总文档与最终集成。各窗口不得回退他人修改。原窗口曾两次因额度中止；用户继续后恢复原窗口，不重复派工，不切换模型。未完成的源码/RED测试均保留，不按文件存在标完成。

## 已有工程证据

- 最小基线55 passed/5 skipped；完整独立PG非live回归1267 passed/0失败/0错误/0跳过，1 live排除及1第三方警告。该次收集早于M2/K3/E2a最终源码，不能代替最终回归。
- T1/M1：Registry→Policy任务目录→模型副本→Executor→原查询/结果审计；共享真实ledger、隔离每任务gateway。真实Java HTTP/固定MCP定向118 passed。
- E1：统一版本与安全阻断合同，历史issue-set与结构有效性分离；E2a原生8场景、观测重评分、原生trace绑定。协调63 passed，实际CLI与verify_run valid；报告blocked，5安全pass/67pending，语义/人工pending，工具注入错误保留。
- K1/K2a：IR摘要绑定审核清单、独立当前ACL/撤回；受限TXT原bytes→逐字行定位→未发布草稿。协调130 passed。
- K3a协调2026-11-17复跑4个retrieval测试文件88 passed/2.04s；独立复审进行中。只内存BM25/RRF与向量协议替身、结构证据三API，无真实embedding质量/持久化/多格式解析宣称。

## 优先未闭环

1. M2 registry.enable：预读注册A的scope加锁后，head可能已是B，必须同时预读generation/config_revision并锁后核对；validation report需绑定当前registration_digest。原独立纯交错可复现用A锁/校验却启用B。必须真实两连接RED/GREEN关闭，不能据早期PG测试签字。
2. M2其他已报项须逐一确认最终状态：Schema引用DAG工作量/序列化上限、过期target_policy拒绝、HTTP解析前字节上限、原工具名带点/未绑定扩展名兼容。M2公开只注册/发现/验证/启停；生产不得直接tools/call绕过Executor。
3. K3复审最终deadline及撤回issue/audit元数据清理、64KiB表格关联、逐provider前治理重检；协调88项通过但等待独立签字。
4. E窗口的knowledge-evaluation-design.md尚未审D，不得提前编码；将用实际TXT/检索/表格/撤回观测生成统一报告，保留runner-v1。
5. M2完成后M3仍未设计/实现：厂区别名/受控来源→授权动态目录→模型动作→本地Registry/Policy/Executor→SDK调用→请求绑定/禁用代次二检。用户优化4不能用“发现连接成功”冒充完成。
6. 最终完整非live/安全/PG/真实SDK、Ruff、wheel/文件保护、文档一致性与handoff必须真实再验。无真实模型、无部署，不重置预算/令牌/旧SQL。

### 2026-11-17 后续检查点

上述1/2/3已闭环：M2协调PG18 passed/36.25s、独立catalog/runtime61 passed/42.87s；enable配置交错真实PG RED/GREEN与独立代码复核关闭，工具窗口完整定向198 passed/Ruff通过。K3a协调/独立88 passed、重点10 passed/Ruff通过，无剩余重要问题。新增接入指南docs/integrations/dynamic-mcp.md只描述当前M2能力。

M3设计dynamic-mcp-inquiry-design.md已独立D通过后触发实施：动态definition固定可信query_at逻辑时钟、实际received_at用UTC/deadline用monotonic；跨轮seen call_id与attempt/wire分别6次硬上限，新增SQL023调用审计由工具窗口独占，旧SQL不改。仍只设备三能力、scripted+真实SDK，不能提前标通过。

知识三场景knowledge-evaluation-design.md也已父窗口D通过后触发，新增evaluation/knowledge_*及独立CLI和产物；旧runner-v1/E2/K3源码冻结。integration_review正在独立只读审新运行器的刺激/评分/trace因果。尚待此增量及M3代码复验后最终全回归，不能套用旧1267数字。

## 环境

PG17完整二进制实际在桌面虚拟化路径：`C:/Users/msm84/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Anlan2Runtime/postgres-17.11/pgsql/bin`。使用dev-postgres.ps1 -Action Env -PgBin该路径，不输出DSN/私密配置。独立主测试库`anlan_engineering_20261116`，先确保public.vector；M2使用自己的隔离库并支持通用测试DSN回退，不drop任何数据库。普通LocalAppData集群残缺，不能据其PG_VERSION重新初始化或覆盖完整集群。

公开语料：用户询问ModelScope，可候选取用但尚未下载/授权发布；来源清单public-corpus-sources.md。公开行业语料不是企业当前事实，公开题不是未见集；真实领域审核不能由AI代填。项目工程状态与本人掌握始终分开。
