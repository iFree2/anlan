# P13 B2 交接：持久化预核查、当前性与完成门控

2026-10-27。B1 实现 `8d552e1` 已经协调验收，实际开始检出为文档提交 `c390d72`，基线验收 `a84eeeb`。沿用 `work/phase-01-wp-04` 分支和当前检出；未创建 worktree、其他会话、子代理或自动化。本文件随 B2 实现提交，确切提交号以本批最终 git log / 会话交付为准。当前本地实现待协调独立验收；不表示 P13 整体完成或已经部署。

## 文件与装配

新增 `preflight/{evaluator,runner,service}.py`、`infrastructure/preflight_jobs.py`、SQL020 和四个 `test_preflight_{evaluator,jobs,service,gate}.py`。扩展协作服务、PrecheckStore、registry 初始化/新申请注册、API lifespan 和既有 conversation freeze。相邻 B1/P12 fixture 按新策略确认实际绑定、取得实际依据并明确选择引用，未关闭门控。B1 目录/绑定服务实现、SQL019/018/017/012、TokenGrant、Identity、额度政策均保持。

`initialize_database` 初始化既有协作表与 SQL019/020，防止旧组合因缺少新表而退回旧完成路径。真实 registry 新申请注册事务同时 ensure_policy；API 启动逐项为缺策略的协作申请记录 required 或 legacy_completed，使用实际 task advisory lock。已完成旧申请仅留历史策略，不制造 binding/job/check，不主动重查；private legacy 不注册共享申请。初始化失败即服务失败，不降级绕过。

API lifespan 在知识 store 选定后装配 `app.state.preflight` 并启动应用内持久化执行循环，退出时取消循环。执行器只使用 FactTools/KnowledgeStore；即使材料服务为 live 配置，也只读取 checkpoint，不调用材料模型。没有独立队列中间件、自由模型综合或付费重试。

## B3 可直接复用的入口

- `PreflightService(dsn, config, service_context_factory, runner=None, *, clock=None)`；应用实例已提供 runner 与业务时钟。
- `recheck(actor, task_id, payload) -> {job_id}`：`RecheckCommand(request_id, expected_material_revision, expected_binding_revision, expected_application_version, reason)`。版本严格正整数；request_id/reason 保留原文并拒绝空白；额外 actor/role/ready/tool/source 字段拒绝。
- `process_next(job_id=None)`：领取一个 queued 或过期 running job，执行只读查询并保存结果；无可领取项返回 None。`serve()` 是应用内恢复循环，不需要浏览器触发。
- `CollaborationService.get` 已返回 `precheck` 共享投影，含 required/legacy、binding_revision、status、check_id/current、问题类别及当前可见 evidence；固定业务时钟以 `clock_mode=fixed_replay` 与 as_of 明示。读取不会调用 FactTools、embedding 或模型，只比较来源元数据；撤权后不返回原始依据。
- 提交/重提冻结 `expected_binding_revision`；完成额外冻结 `expected_check_id`、`applied_knowledge_citation_ids`。字段保留可缺省以便旧 HTTP/卡片进入受控 409，而不是在解析时补最新版。客户端 ready、任意引用、actor 覆盖均不可用。
- conversation freeze 只从服务端当前共享快照冻结 binding/check；普通聊天/模型提案的采用引用集合固定为空，确认无法完成。B3 必须新增显式、结构化的人工引用选择流程，再把所选集合冻结进完成载荷；不得从模型文字或“确认”猜测选择。

尚未新增对象/预核查 HTTP 路由、UI、双浏览器或事件对象复用。B3 接 `BindingService` 的目录/确认与上述 recheck/get 投影，沿既有协作完成命令调用门控即可，不应另建 ready override。

## PG 表与不可变记录

SQL020 独立新增：

| 表 | 作用 |
|---|---|
| precheck_jobs | EvidenceKey 四版本、真实发起人、request_id/refs/材料安全快照、cause、PG ordinal、状态与 lease |
| precheck_attempts | 每次领取独立 attempt_id，PG 开始/结束时间与 running/expired/completed 历史 |
| precheck_results | 不可变 check_id、job/attempt、三项观测、来源摘要/引用/ACL 摘要、规则版本/业务时钟/截止期/问题与 assessment |
| precheck_recheck_commands | tenant+actor+request 命名空间、完整载荷与 job 回执；变载荷/跨任务冲突 |
| precheck_cycles | 要求补充时冻结的绑定版本与来源基线，供材料或绑定或源依据变化的重提比较 |

自动 job 对同 EvidenceKey+automatic cause 唯一；显式重查用真实 actor/request 命名空间生成独立 cause，同 request 仅回放。job 输入、results、重查回执、cycle 不可改写/删除；终态 attempt 不可改写。job/attempt 复合外键防止结果错挂尝试，完成 job 不能重新排队。SQL020 使用 PG13 支持的 DROP/CREATE TRIGGER 形式；实际运行环境仅 PG17，未声称实跑 PG13。

## 锁、事务与恢复

协作提交/重提沿用真实 registry task 会话锁 → actor/request 事务锁 → application FOR UPDATE，在同一事务保存状态、job、业务事件、通知与命令回执。save_receipt 前失败会全部回滚。缺绑定或冻结版本不符拒绝提交。under_review 的缺口/失败不阻止读取或要求补充。

claim 用短事务 `FOR UPDATE SKIP LOCKED`，lease 用真实 PG `clock_timestamp()+30 seconds`；业务固定回放时钟不影响 lease。领取后释放连接/任务锁才进行只读 I/O。事实资质→区域顺序执行，知识并行，问题由本轮作业方式/对象与绑定 IDs 构造并限长。

写回先取得与 registry 相同的实际 PG task advisory key，再用真实 actor 重新授权、比较 checkpoint/pending、材料/绑定/申请版本、最新 job ordinal 与来源；旧轮次结果留在历史并记 stale。最后锁 job 行、核对当前 lease/attempt，保存 append-only result。过期尝试不能写回；同尝试重复 finish 返回原记录。遇 task 锁忙主动令本尝试 lease 到期，下一次领取保留 expired 尝试。协作边界及材料 HTTP 的读取/修改/恢复仅对 TaskBusy 做最多约 0.5 秒的有界重试，不重试业务冲突；已保留但未完成的材料 operation 继续要求原恢复流程，不会重复调用分析器。

完成命令在同一真实 task 锁与协作事务内比较本轮绑定/check、完整当前快照、有效期、文件摘要/ACL、知识版本/内容摘要/withdrawn/current/ACL；知识 document/chunk 行通过 FOR SHARE 锁到完成事务提交。人工所选引用必须非空、无重复且属于本轮有效引用；人工结论不能把异常或 unknown 变 ready。评估必须是 active+normal、无业务 reason、有效来源与当前引用，截止为查询开始业务时钟+10分钟和已知来源截止的最小值。

本地事实文件使用有界读取的字节 SHA256 核对当前性，外部文件编辑者不受 PG 行锁管理；本期没有源管理写 API，不能声称文件系统与 PG 跨系统原子提交。知识来源的实际 PG 写入竞争已单独验证。已完成人工核查后的来源撤回只显示历史依据过时，保留当时结论与引用。

## 补充与重提

要求补充时保存当前绑定与来源基线。重提允许材料 revision 增加、绑定 revision 实质变化，或源资料更新后先显式重查得到不同的当前来源批次；不用改无关材料。旧未绑定 under_review 申请可先要求补充，再由申请人确认绑定并以相同材料 revision 重提。安全人员只读/重查/要求补充，不能替申请人改绑定。

## B2 基线验证与交付证据（449dd21）

真实 PostgreSQL 17.11（server_version 170011），项目 loopback `127.0.0.1:55432`，独立库 `anlan_p13_b2_20261027`。使用 dev-postgres Start/Env 后只替换库名；为知识测试在该库显式创建 vector extension。初轮仅包含本批试验的库保存在 `anlan_p13_b2_initial_20261027`，未删除数据；正式 B2 库为重新创建的独立空库。

RED/修复过程见 `evidence/b2/red-green-notes.md`；原始失败组合、租约竞争 RED/GREEN、最终组合、来源行锁/旧无绑定路径及 Ruff/wheel 证据分别保存。

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 最终指定组合 | **170 passed / 0 failed / 0 errors / 0 skipped**；终端 375.27s，XML suite 374.999s | `regression-green.xml` |
| B1 策略保持加强验证 | 真实 B2 完成后仍 required，旧已完成才 legacy；1 passed / 12 deselected；不与主组合重复相加 | `policy-preservation-green.xml` |
| 真实来源行锁与旧未绑定补充路径 | 2 passed / 25 deselected；两项亦已纳入最终 170 项，不重复相加 | `additional-green.xml` |
| queued/running 实际新进程恢复 | 两个用例均通过，包含硬退出与过期尝试审计；包含在最终组合内 | `regression-green.xml` 中 jobs 的两个 real_new_process 用例 |
| 全目录 Ruff | 0 finding，空数组 | `ruff.json` |
| 最终 wheel 离源码验证 | **107 modules / 20 resources / 9 CLI**，SQL020 与全部旧资源逐字节校验 | `wheel-layout-release.json` |

449dd21 基线制品 `.runtime/p13-b2-release-dist/anlan-0.1.0-py3-none-any.whl`，SHA256 **`c785f33c7460c7b871ba1547c8f7f2bd6d49a9636ba97d5d583b1e552bd7622b`**。`wheel-layout.json` 与 `wheel-layout-final.json` 是前两轮历史构建，分别对应 `.runtime/p13-b2-dist/`、`.runtime/p13-b2-final-dist/`，不能替代 release 报告。

最终主组合命令如下。使用显式文件集合，未以该结果冒充整个仓库的 B4 Gate；本组合没有 live 用例被选择，没有 skip。

```powershell
. ./scripts/dev-postgres.ps1 -Action Env | Out-Null
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_DATABASE_URL -replace '/anlan_dev$', '/anlan_p13_b2_20261027'
.venv/Scripts/python.exe -m pytest -q tests/test_preflight_evaluator.py tests/test_preflight_jobs.py tests/test_preflight_service.py tests/test_preflight_gate.py tests/test_preflight_contracts.py tests/test_preflight_catalog.py tests/test_preflight_bindings.py tests/test_preflight_store.py tests/test_collaboration_service.py tests/test_collaboration_api.py tests/test_collaboration_recovery.py tests/test_collaboration_conversation.py tests/test_conversation_api.py tests/test_service_reliability.py tests/test_audit_only_budget.py tests/test_package_layout.py -m 'not live_model' --junitxml=docs/phases/phase-13-preflight/evidence/b2/regression-green.xml --tb=short
.venv/Scripts/ruff.exe check src tests evals scripts deploy --output-format json --output-file docs/phases/phase-13-preflight/evidence/b2/ruff.json
uv build --wheel --out-dir .runtime/p13-b2-release-dist
.venv/Scripts/python.exe scripts/verify_package_layout.py --wheel .runtime/p13-b2-release-dist/anlan-0.1.0-py3-none-any.whl --output docs/phases/phase-13-preflight/evidence/b2/wheel-layout-release.json
```

wheel verifier 输出为排他创建，复验应指定新的报告路径。上述追加策略加强测试仅增强断言；449dd21 基线的生产代码与当时 170 项和 wheel 证据一致。后续协调 Minor 修复见下一节，不包含在这个基线 wheel 中。

## 协调 Minor：区分执行失败与依据过时

协调另库基线 49 项通过、全目录 Ruff 通过，代码审查无 Critical/Important，提出 runner 异常投影 Minor。本次只修复两个服务模块、相关测试与交接证据，不改 SQL/完成权限、不启动 B3。

`process_next` 捕获 runner 异常时持久化 `execution_status=failed`、`ready=false` 和安全类别 `source_unavailable`；不持久化异常文本/trace，也不制造 valid_until。新增 `inputs_current` 只核对当前输入和最新轮次，失败写回据此单独记录是否 stale；证据的 `current` 对失败始终为 false。完成门控仍拒绝该 check，不能用人工结论或任意引用覆盖。

授权共享投影将执行失败显示为 status/execution_status=failed；输入未变时 stale=false，输入已变时 stale=true。current=false 仅表示没有有效依据，不能单独当作失败或过时。新排队重查显示 queued/stale=false，失败审计和原 attempt/result 保留，显式重查可生成新的有效 check。新字段均为服务端派生，客户端没有覆盖入口。

针对性真实 PG RED 为两个 `status: stale != failed`；另外补充 queued 不能仅因 current=false 而标 stale 的 RED。证据为 `failed-projection-red.xml`、`failed-projection-queue-red.xml`、`failed-projection-green.xml`，相邻回归与全目录 Ruff 结果在 `failed-projection-regression-green.xml`、`failed-projection-ruff.json`。本次未重建 wheel，后续交付必须包含源码修复后重新构建的制品，不能把 449dd21 的 wheel 当作已含本补丁。

实际结果：针对性 2 passed / 14 deselected；随后在同一真实 PG17.11 隔离库 `anlan_p13_b2_20261027` 跑 evaluator/jobs/service/gate 加 collaboration service/API，**65 passed / 0 failed / 0 errors / 0 skipped，124.52s**。针对性两项已包含于 65 项内，不相加。全目录 Ruff 为 0 finding。未重新跑全仓、真实模型或 SSH，原 dirty 路径保留。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_preflight_evaluator.py tests/test_preflight_jobs.py tests/test_preflight_service.py tests/test_preflight_gate.py tests/test_collaboration_service.py tests/test_collaboration_api.py -m 'not live_model' --tb=short --junitxml=docs/phases/phase-13-preflight/evidence/b2/failed-projection-regression-green.xml
.venv/Scripts/ruff.exe check src tests evals scripts deploy --output-format json --output-file docs/phases/phase-13-preflight/evidence/b2/failed-projection-ruff.json
```

未执行用户未提交的 test_tool_loop_live.py、真实模型/供应商测试、SSH、部署或额度重置；保留 roadmap/status 的原 dirty、phase-10 目录和 .superpowers/。本批不修改总 README、阶段 README、acceptance 或 coordinator-check，不自行启动 B3。
