# P12 B4 交接：集成 Gate、双浏览器与恢复

日期：2026-10-24（Asia/Shanghai）。基线 `fd783e1`（B3 实现 `4726f27`、交接 `cdf742d`、协调验收 `26774a9`）。本批实现 SHA：`c9a096e641c706588bdb884627518bf6b725f15e`。本文及证据以随后独立文档提交交付，可用 `git log -1 -- docs/phases/phase-12-dual-role/batch-04-handoff.md` 查询。

**B4 独立审查收尾，2026-10-25恢复（审查基线 `51d088b`，恢复 HEAD `80ee20e`）：**有效 PG 目标防护、实际 serving PID/端口退出与安全清理已完成，实现提交 `27325580c98c47d9067d28c8ab9c4c784e3edd36`。最终新全套 **905 passed / 0 failures/errors/skipped / 1 live deselected**。本次不进入 B5，交协调验收。后文原820项与浏览器/wheel证据保留，不能视为新增防护断言已覆盖。

沿当前 local 检出串行实施，没有 worktree、子代理、后续会话或跨会话消息。总 README 与 acceptance.md 由协调维护，本批只在本文逐项对照 G4。原用户 dirty 路径保持不动：roadmap/status 的 P10 内容、P10 目录、test_tool_loop_live.py、.superpowers。没有 SSH、云端部署、真实供应商请求、预算改动或录制。

## 实际修改

- `interfaces/collaboration_conversation.py`：在同一授权任务锁内检查空 checkpoint，抛受控 InvalidTransition。绑定 HTTP 409，已绑定会话显示 unavailable；显式 recover 恢复同一 task/owner，不创建另一份申请，不重试模型。
- `collaboration/service.py`：同一空 checkpoint 窗口下，共享读取与直接提交确认候选也返回受控409；补充 RED 真实复现候选 freeze 读取 revision 的 KeyError 后，增加相同边界检查，避免只修页面绑定。
- `infrastructure/collaboration.py`：真实并发发现 task 主键之外的 tenant/task 唯一索引也会冲突。幂等注册改为 `ON CONFLICT DO NOTHING`，仍先锁定并核对原 registry 的 tenant/user。未改 SQL、归属或权限策略。
- `interfaces/console/assets/app.js`：快照比较先规范对象键顺序，保留数组顺序；同内容 JSONB 顺序变化不再重建冻结卡片，真实 revision 变化仍刷新。
- 新增 `tests/test_collaboration_recovery.py`、`tests/test_collaboration_release.py`、`scripts/verify_collaboration_release.py`。

没有新增审批、开工授权、材料预核查主流程、真实设备、P9/P10 或架构重构。材料/事件与协作 PG 事务边界保持原样，没有把模型调用放入协作事务。

## RED / GREEN 与工程 Gate

证据目录：`evidence/batch-04/`。

提交的 RED JUnit 的 pytest 展示行仅移除行尾空白，以通过 Git diff 检查；测试数量、失败类型、断言和 traceback 未改，原始 XML 保留在 ignored `.runtime/p12-b4-*.xml`。最终清单 SHA 对应提交的规范化证据。

本目录局部 `.gitattributes` 禁止 Git 再次转换证据行尾，保留其实际 bytes；manifest SHA 同时核对工作目录与暂存 blob，不影响其他目录的换行策略。

| 问题 | 真实 RED | 修复与 GREEN |
|---|---|---|
| B3 空 checkpoint Minor | registry+draft 提交后、首次 reserve 前中断；绑定 KeyError task_id | 受控 409 / unavailable，同 task recover，另一人 recover 404；初次 1 passed |
| 同窗口直接确认候选 | 已绑定会话直接 POST candidate，freeze 的 revision KeyError | 共享读取与候选均409，显式恢复后原task可读；最终相邻14 passed |
| 并发幂等注册 | 首轮全仓 UniqueViolation，20 波 × 8 并发新任务回归再次复现 tenant/task 唯一约束冲突 | 一行 SQL；恢复+存储 16 passed in28.97s |
| wheel 静态资源 | 原校验未包含四份控制台资产，新增测试失败 | 新 Gate 校验全部 SQL、原静态资源及 console HTML/JS/CSS 的实际 bytes；损坏 api.js 拒绝 |
| 快照对象键顺序 | 真 JS/Node VM 回归显示相同载荷键顺序变化导致 renderCount=1 | 对象规范比较，renderCount=0；真实 revision 变化 renderCount=1 |

最终两份新增测试及相邻控制台回归：**14 passed in79.54s，0 failures/errors/skipped**。该运行包含真实 PG 与四个新进程，不与其他运行相加。

首轮全仓：**815 passed / 1 failed / 0 errors / 0 skipped / 1 deselected，707.70s**；失败即前述真实并发缺陷，未改报告为通过。第二轮因随后发现并修复 UI 比较问题而主动停止（已核对本批 pytest PID 8936/31164），不计通过。最终全仓：**820 passed / 0 failures / 0 errors / 0 skipped / 1 deselected，637.09s**。Ruff `src tests evals scripts deploy` 实际通过，`git diff --check` 与暂存 diff 检查通过。

在上述三项修复后曾完整得到 **820 passed / 0 failures/errors/skipped / 1 deselected，675.55s**。随后的收尾检查沿同一空 checkpoint 窗口补查直接候选，复现另一处 revision KeyError；已扩展原恢复测试并在共享读取处补两行检查。该次820结果保留为 `pytest-before-final-empty-guard.xml`，不能替代最后两行保护后的全仓结果。

唯一 live 用例是用户未提交的 `tests/test_tool_loop_live.py::test_live_deepseek_selects_tools_and_summarizes_results`。它没有默认 opt-in/skip 防护，故全仓显式使用 `-m 'not live_model'`，准确记为 1 deselected，不能声称默认跳过或零跳过的付费实测。其文件未修改。

本地 PG17.11：`127.0.0.1:55432` 的新库 `anlan_p12_b4_20261024`，两份本地 DSN 均指向此库。已实际执行 PG 测试，不使用 skip fallback。新库启用已安装的 pgvector 0.8.6；不覆盖已有服务配置、旧库、旧行或账本。

## 最终 wheel 与进程恢复

最终 wheel：`.runtime/p12-b4-dist/anlan-0.1.0-py3-none-any.whl`。

SHA256：`6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`。

`wheel-complete.json` 记录 21 份完整资源（全部旧/新 SQL、原资源、四份控制台文件）、四个真实进程 PID、实际 `anlan.__file__` 均来自该 wheel，以及每次默认知识组合为 KnowledgeStore。服务在系统临时目录以 `python -I` 启动，cwd 在源码目录之外；配置显式 scripted_double，数据库只允许 loopback。`package-complete.json` 另验证全部模块实际来自 wheel，并执行九个兼容 CLI help。

恢复链：保存完整 submit 卡片→结束进程→新进程比较完整 frozen payload/双版本→真实协作 PG 提交后、会话回执前 `os._exit(91)`→新进程用原 request_id/原载荷重放，submit 事件与通知各一次→补充/重提→保存 complete 卡片→再次新进程恢复并确认→双方同 task、不同 conversation 读到 version5/revision2。故障注入只存在本地验收 harness，不进入产品启动路径，也不调用模型供应商。

另用该最终 wheel 在源码之外的临时 cwd、`python -I`、本地8015端口启动，创建 `p12-b4-complete-wheel-applicant/manager` 两个新隔离浏览器上下文，用原两份本人配置恢复最终浏览器业务 task。双方**当前任务 code** 都是 `44dced2e-2db7-5667-b06d-960a7b36bdd3`；管理端恢复知识 ok、旧核查 stale 和人工反馈。截图 `final-wheel-*.png` 与 `browser-wheel-provenance.json` 记录实际 wheel 模块路径/cwd/精确SHA。核对 serving PID28684、launcher11780 后，仅停止该服务并关闭本批新页面。更早一对 wheel 自检上下文亦已关闭，最后两行空 checkpoint 保护后的证据以此组为准。

## 两个独立浏览器上下文

使用 Chrome DevTools 两个隔离 context：`p12-b4-applicant`、`p12-b4-manager`；两份不同 token 的本人配置，凭据只在页面内存，local/session storage 均为空。未使用 B3 自检截图或其 Unavailable 注入充当 Gate。

最终源码业务链 task：`44dced2e-2db7-5667-b06d-960a7b36bdd3`。

- 申请人 `applicant-demo`：conversation `3227db83-d78f-446b-85b4-2fe9f863e742`。
- 安全人员 `safety-manager-demo`：conversation `d3467d69-6c22-4c43-b5a3-409bcdf35882`。
- 创建前确认→缺附件→补齐到材料 v2→选择指定安全人员并确认 submit→安全人员要求 FINAL-B4 东侧2号具体点位→断网/重连补读一次要求→申请人补充到 v3→确认 resubmit→安全人员确认材料核查完成，application version5/completed_material_revision3。
- 真实点击模拟一条未戴安全帽事件、发起核查、保存 needs_verification 反馈。三项依据均 ok，知识引用三条；事件/review/feedback actor 都是安全人员。补材料后 currentness=stale_material，原报警 active。
- `browser-final-state.json` 是同一 task 的受限 HTTP/事件/收件箱快照，双方读对方私人 conversation 均 404。截图明确核对当前任务 code，不能只用侧栏列表中的编号冒充当前选择。

桌面 1440×1000 和移动端 390×844 都通过无横向溢出测量；移动端实际展开并选择事件，详情位于可滚动 task-sidebar。最终图片以 `final-` 开头，包括双方桌面/移动完成、知识反馈与过时核查。中间截图不作为最终版本通过证明。

异常验证包含：离线收件箱恢复、唯一要求消息、普通聊天不执行候选、取消完成卡后重新候选再确认、轮询保留草稿、键顺序修复后初始卡片经过轮询仍为同 DOM；同身份切会话时延迟旧快照没有切回，换到另一配置后释放旧响应没有出现申请人私聊哨兵。更换移动/桌面仿真会重载并清除内存凭据，重新选择本人配置后恢复；不声称凭据跨刷新持久化。

如实保留验收过程中的错误：人为停服务/断网产生连接拒绝；旧 DevTools uid 因页面更新失效，重新取 snapshot 后操作；一轮 resubmit 遇受控 409，读取后再次显式确认只提交一次；临时只读证据采集遇锁冲突后增加有界只读重取。未自动重发业务命令、重试供应商或把这些中间工具失败记为通过。

## 知识组合与 G4 对照

默认 `create_app/serve` 保持原 LocalEmbeddings + KnowledgeStore 组合。新租户沿既有 `KnowledgeStore.ingest` 导入六份仓库公开 SYNTHETIC 文档，allowed_users 为空，使用已有本地 bge-small-zh-v1.5 神经向量与固定制品摘要；检索合法命中。未复制旧租户私聊或私人知识。知识不可用的 unknown/evidence_gap 仍由既有 perception 合同及本批全仓测试覆盖；不能把脚本模型或合成知识命中说成真实模型质量/泛化验证。

演示配置使用固定的合成回放时钟 `2026-09-22T04:00:00Z`，不是2026-10-24的实时现场状态。最终浏览器业务在实际新服务进程中再次恢复：`browser-process-restart.json` 记录前后实际 serving PID，双方 conversation、同 task 的业务历史/收件箱、事件与反馈逐字段一致；比较只选该 task，不把并行 wheel 验收产生的其他合成 task 通知混为变化。

另独立直接 HTTP 检查四类协作命令：未分配安全人员/另一申请人/legacy/跨租户身份共16次写入全404，匿名四次全401，申请 version 保持2。`http-write-matrix-and-gap.json` 同时记录显式知识故障组合：原合同工具返回 `error/knowledge_unavailable`，candidate 的 unknown_observation_ids 含 o3 且保留 evidence_gap，原报警仍 active。临时验证最初误以为工具 outcome 必为 unknown，实际读取既有合同后纠正验收断言；没有改产品返回值迎合断言，也没有改掉默认成功知识组合。

| G4 条目 | 证据与状态 |
|---|---|
| 每批红绿、PG、Ruff、准确全仓数量 | 原820项保留；harness收尾后新增完整905 passed、0 failures/errors/skipped、1 live deselected；见追加记录及gate-result |
| 独立双浏览器完整往返 | 最终 task/两个 conversation、browser-final-state、final 截图 |
| 第三者/跨租户/匿名 HTTP、通知、SSE | recovery 直接 HTTP 矩阵；全仓 collaboration API/conversation/events 撤权与隐私测试 |
| 旧卡片/并发/重放/重启 | PG 并发、旧版本、事务回滚/同收件人跨 task 顺序；真实四进程 wheel Gate；实际浏览器异常 |
| 桌面/390×844 | 最终两角色截图、实测 scrollWidth≤innerWidth；后端测试独立于按钮隐藏 |
| wheel/资源/敏感信息 | 21 份资源逐字节、离源码 HTTP、全模块 wheel imports、凭据扫描与固定错误边界 |
| B3 空 snapshot Minor | 已关闭，原 task 显式 recover，不冒用 owner |

## 复现与下一步

```powershell
. scripts/dev-postgres.ps1 -Action Env
# 将两份本地 DSN 的库名设为新的 B4 隔离库；不打印连接串。
.venv/Scripts/python.exe -m pytest -q -m 'not live_model'
.venv/Scripts/python.exe -m ruff check src tests evals scripts deploy
uv build --wheel --out-dir .runtime/p12-b4-dist
.venv/Scripts/python.exe scripts/verify_collaboration_release.py --wheel .runtime/p12-b4-dist/anlan-0.1.0-py3-none-any.whl --config .runtime/p12-b4-demo/service.json --output .runtime/<新的证据文件>.json
```

私密演示配置保留在 `.runtime/p12-b4-demo/`（service/applicant/safety-manager.json），不进 Git。本批服务/页面仅清理本人创建且核对 PID/context 的资源，保留 PG 与演示业务记录。

本批 G4 工程与浏览器验收项已满足，没有剩余本批 Gate 项；交协调独立复核后可进入 B5。本会话按用户要求未派审查代理，已自查最小 diff 与权限/事务边界，未将自查冒称独立审查，也未自行创建 B5。云端替换、有限 live 和双角色女声视频尚未完成，不宣称生产安全、模型泛化或整个 P12 完成。

## 独立审查 Important：发布 harness 的实际 PG 目标

审查复现了旧 `main` 只看 host 的缺口：localhost 配远端 hostaddr、继承 PGHOSTADDR/PGSERVICE，以及直接调用 verify 绕过 main。已核对本机 psycopg 的 get_param/split_attempts/_resolve_hostnames 实现，hostaddr 与 PG 环境确实可决定实际目标。协调确认原实跑环境的相关 PG 设置未启用，本次启动前读取非空 PG* 名字列表也为空；**此前本地证据仍有效，没有证据显示曾连接远端**。

本次只改 `scripts/verify_collaboration_release.py`、`tests/test_collaboration_release.py` 及本交接/证据，没有修改应用源码。因此应用 wheel SHA 仍为 `6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`；harness 自身 SHA 单独记录于 `wheel-target-guard.json`。

- 同一 `loopback_dsn` 在 verify 入口和每次 WheelServer.start 边界执行；后者在同一环境快照上验证后构造子进程环境，覆盖两份 ANLAN 数据库变量。
- 只支持显式单一 TCP loopback；host 与任何显式 hostaddr 都必须合法 loopback，拒绝 service、多主机/多地址、多端口、缺省 host、空目标与非法端口。localhost 固定数值 hostaddr=127.0.0.1，显式 IPv6 loopback 保持 ::1；不做 DNS 查询。
- 保守拒绝所有非空 PG* 环境设置，包括 PGHOSTADDR/PGSERVICE/PGSERVICEFILE/PGOPTIONS/PGPASSWORD，并从子进程环境移除全部 PG*（包括空值）。需要的认证/SSL等应放进明确的本地 DSN，不能通过继承环境暗中补足。
- 非法连接串由固定错误替代并抑制 libpq 原异常链，不输出 DSN、密码或环境值。仍要求 scripted_double，仍用四个实际新进程和非覆盖证据文件。

纯离线 RED：**70 failed / 0 errors / 0 skipped / 7 deselected，33.66s**，均由缺失防护或子环境未清理导致；Popen、psycopg sync/async connect、socket connect 与 DNS 均有 stub，实际子进程和连接为0。203.0.113.10、2001:db8::1、example.invalid 只出现在离线拒绝输入，未作远端探测。GREEN：**70 passed / 0 failures/errors/skipped / 7 deselected，6.26s**；包括合法显式 loopback 兼容和启动边界环境变化复核。之后只修正了测试参数名以通过 Ruff，未改变防护语义。

目标防护阶段的 `wheel-target-guard.json` 已实际完成本地 PG 四进程恢复，记录 hostaddr 固定、PG 环境清除及该阶段 harness SHA；原 wheel/浏览器证据不覆盖。该阶段相邻四文件新回归 **97 passed in106.70s，0 skipped**。首次完整回归中的 wheel 恢复用例失败及随后单项 **1 passed in56.57s** 均保留；不能以单项通过替代全套。最终结果见下述恢复收尾，旧820计数未改写成新断言已覆盖。

## 2026-10-25 恢复：实际进程退出与 Windows 清理

上一轮完整结果为 **889 passed / 1 failed / 0 errors/skipped / 1 live deselected，731.73s**。失败在业务/恢复断言之后的 TemporaryDirectory 清理，WinError32；保留 `pytest-target-guard-first-failed.*`，不改写为通过。恢复初次组件运行时本地 PG 未启动，得到 **87 passed / 1 error，14.59s**；确认仅本机55432后通过现有 Start 脚本恢复 PG17.11，再运行，不将该环境错误计作产品修复结果。

没有仅凭 WinError32 就加入等待。可控本机 launcher 探针（0 PG/模型请求）记录：launcher PID29508 与实际 PID27936 不同；launcher wait 返回时 serving 尚未退出，之后约0.21s才退出，无需另行终止。恢复初次进程快照未见残留，但后续确实发现了一个中间运行遗留的进程，见下述处置，不能把非原子快照当作无残留保证。旧失败的 marker 已被清理，不能由此反推该次失败时一定有/没有孤儿。探针原 `port_closed` 字段来自连接探测，不作为最终端口证据。

最终修复仍只在 harness/test 内：

- 直接启动 CPython 的 base interpreter，并显式提供本 venv 依赖目录；避开 venv redirector。每代 readiness nonce 与 marker 均要求 serving PID 严格等于 Popen PID，拒绝错代/错进程，不按任意 PID 终止进程。
- `stop` 对持有的实际 Popen 句柄 terminate/wait，必要时 kill/wait；崩溃91也显式收割。Windows 读取 IPv4/IPv6 系统监听表确认端口关闭，不将连接超时/权限错误解释为关闭。不修改应用或额外重发业务、模型、工具。
- 只有全部受控进程退出且端口关闭后，才清理本次创建的临时根目录。验证系统 temp 直属路径、专用前缀、非 symlink/junction；其他路径或未确认退出拒绝清理。仅 WinError32 最多等待1.95s，其他错误原样抛出；永久占用仍失败，不忽略 cleanup 错误。

新增退出/清理 RED：**11 failed / 77 deselected，3.09s**。端口连接推断的补充 RED **2 failed / 1 passed / 88 deselected，1.31s**；真实自有 listener 的 RED 确认关闭后仍被旧探测误判，合并4项 RED 保留。中间端口探测版组件结果 **110 passed / 1 failed，74.17s**，以及随后停止的中间完整运行日志保留，不计最终通过。

最终离线/控制验证 **85 passed / 7 deselected，8.36s**，相邻四文件 **112 passed / 0 failures/errors/skipped，96.33s**。`wheel-target-lifecycle.json` 真实四进程通过，PID348/12648/28752/18828 的 launched_pid=serving pid，端口63017在每次退出后关闭，退出码包括预期91，临时目录一次清理完成，四次默认 KnowledgeStore。应用 wheel SHA6024af…保持不变；本次 harness SHA为 `96d5052561cb981acab087f0ad40e2787414824dba55038e06e2725c03f76dc6`，与提交的脚本字节相同。

最终新完整回归：**905 passed / 0 failures / 0 errors / 0 skipped / 1 live deselected，pytest报告73451.27s（20:24:11）**。JUnit suite时间73451.237s，其中既有 `test_hard_process_exit_after_material_merge_can_recover` 报告72813.765s；其后单项复核 **1 passed in3.72s**。长计时原因未从现有证据确定，原值完整保留，不将该总计时当作性能结论，也不以单项复核替代905项全套。`pytest-target-guard-final.*` 与 gate-result/manifest 记录当前结果；旧820、889/1失败、单项通过分别保留。

最终进程扫尾还识别出此前被停止的中间 pytest PID10660 遗留的 serving PID30960（目录 `anlan-b4-wheel-cxv0qiql`、本机端口62584）。核对父PID、原测试wheel/config路径、marker和readiness代次一致后，只停止这个持有的进程对象并等待退出，系统监听表确认62584关闭，旧目录保留未递归删除。`interrupted-run-process-cleanup.json` 记录该事实；这说明此前“无子进程”的瞬时快照存在中断竞态。最终包括venv命令形式的精确B4 serving签名扫描为0。本次正常四进程 Gate 的退出证明与这一中断残留处置分别记录，未掩盖孤儿或全杀Python/PG。

本次Ruff `src tests evals scripts deploy` 与diff检查通过，只提交所拥有的harness/test/交接/证据；应用源码和用户dirty均未改。本项Important及退出/清理收尾完成，交协调独立验收，未启动B5、部署、真实模型或录制。
