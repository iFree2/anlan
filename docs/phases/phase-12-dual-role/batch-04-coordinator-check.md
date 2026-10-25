# P12 B4 协调验收

日期：2026-10-24（Asia/Shanghai）。初始实现 `c9a096e641c706588bdb884627518bf6b725f15e`，交接/证据 `5f8125a`；基线fd783e1。G4完成需关闭下面的harness安全边界，不能仅凭已有回归启动B5。

## 独立复验与证据核对

使用本地PG17隔离库 `anlan_p12_b4_20261024`，先运行dev-postgres Start/Env并仅替换本地DSN库名，不打印连接串。协调实际执行：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_recovery.py tests/test_collaboration_release.py tests/test_collaboration_store.py tests/test_collaboration_console.py -m 'not live_model'
.venv/Scripts/python.exe -m ruff check src tests evals scripts deploy
```

结果 **27 passed in74.14s，0 skipped**，Ruff通过。覆盖真实PG、空checkpoint/显式恢复、并发注册、身份HTTP边界、四个wheel新进程、卡片/回执恢复、控制台轮询和资源完整性。

协调读取最终JUnit确认820 tests、0 failures/errors/skipped，控制台637.09s；实施明确排除1个用户未提交live用例，未为追求零排除而付费。820属于实施全仓运行，27属于协调定向运行，不相加。另逐个核对manifest的32份证据文件SHA全部一致，实际wheel SHA为 `6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`，与报告一致。

目视检查最终申请人完成页与wheel管理端恢复/知识页：共享同task、材料核查完成、knowledge依据ok、旧核查材料已变化、反馈保存和原报警active均有实际画面；原始进程恢复记录的前后serving PID不同，受限业务快照逐字段相同。此为证据复核，不冒称协调重复操作了整条浏览器链。

## 审查与待修项

只读审查者确认：B3空checkpoint Minor在adapter和CollaborationService两处同锁保护及恢复测试中已关闭；并发注册修复与快照规范比较、wheel隔离和四进程恢复无新增应用授权阻塞。

Important一项：`verify_collaboration_release.py` 的loopback检查仅在main读取dsn.host；host=localhost且hostaddr为远端，或继承PGHOSTADDR/服务参数，实际libpq目标可能不同。直接调用verify也绕过main检查。审查者依据已安装psycopg的hostaddr优先及PG环境默认参数读取源码确认，未连接远端；协调核对script调用链后接受该问题。

协调检查当前PGHOST、PGHOSTADDR、PGPORT、PGSERVICE、PGSERVICEFILE、PGDATABASE、PGOPTIONS均未设置，因此不将已完成本地验证说成曾连接远端。已有本地证据仍有效；缺口是harness未来可能误连的防护合同。

已向原B4会话发出范围内收尾：先用stub阻止Popen/connect的离线RED，复现直接入口、hostaddr/环境/服务覆盖等拒绝缺口；统一在verify/进程边界校验实际目标，清理或拒绝PG覆盖，保持错误不泄密，再复验真实loopback路径和准确回归。禁止远端探测/云端或模型调用，不修改应用功能或预算。修复通过、证据更新并复核后再放行B5。

## 防护修复中的独立定向验证

实施会话修复harness与测试后、最终非live全仓仍运行时，协调只读核对入口及子环境边界，并独立执行纯离线定向：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_release.py -k 'target_rejected or explicit_loopback or rechecks_environment'
.venv/Scripts/python.exe -m ruff check scripts/verify_collaboration_release.py tests/test_collaboration_release.py
```

实跑 **70 passed, 7 deselected in16.25s**，Ruff通过。此处7项是-k过滤的非本次目标用例，不是付费调用或PG跳过。拒绝路径由stub阻止Popen、sync/async connect、socket与DNS；没有远端探测。原代码应用wheel不变；协调等待最终修复提交、完整回归/证据与只读复核，**此记录还不将B4标记通过**。

## 2026-10-25 原会话恢复

检查到B4收尾turn为interrupted/idle，未提交防护与新测试均保留，未把中断当作完成。已按用户“继续”在原会话恢复，不创建重复批次。其最新完整非live轮次为889 passed、1 failed、1 live deselected；实施记录指出四进程业务断言完成后Windows TemporaryDirectory清理出现WinError32，单项诊断通过不能代替完整Gate。

协调要求先核对venv launcher与实际serving PID均已退出、端口关闭及临时目录句柄；不能未经证实就认定短暂文件释放，更不能用重试掩盖孤儿服务。若确证仅共享句柄释放，可对winerror32做短时有界等待，其他错误继续抛出；只清理本批实际创建且核对的进程/目录，不全杀Python/PG、不越界递归删除、不重发业务或模型。修复、准确回归与证据提交后再最终验收。

在退出/清理修复源码已冻结、实施最终完整回归仍运行时，协调独立执行 `pytest -q tests/test_collaboration_release.py -k 'not wheel_process_restarts'`，实跑 **91 passed, 1 deselected in10.51s**，随后对应script/test的Ruff通过。该运行包含目标拒绝、PID/nonce、受控退出、真实本机listener、清理路径/WinError32边界与资源/Node验证，不包含被-k排除的四进程用例；不把它称为完整Gate。四进程最终结果及完整回归仍待交接/提交核对，修复也已交只读审查者复核。

## 最终验收与放行B5（2026-10-25）

最终harness实现 `27325580c98c47d9067d28c8ab9c4c784e3edd36`，交接/证据 `45b253e`；应用源码仍为c9a096e对应版本，应用wheel未变。原PG目标Important和退出/清理问题已修复，审查者对最终源码/证据只读复核后无Critical/Important/Minor；未运行测试或连接。提交后harness SHA与被审查版本及lifecycle证据一致：`96d5052561cb981acab087f0ad40e2787414824dba55038e06e2725c03f76dc6`。

协调额外在本地隔离PG实际执行 `pytest -q tests/test_collaboration_release.py -k wheel_process_restarts`：**1 passed, 91 deselected in39.94s**，完整经历四个实际服务进程、持久化确认、回执前中断与重放、端口关闭和受限目录清理；随后 `ruff check src tests evals scripts deploy` 通过。它与先前91项是两次运行，不冒充单次完整全仓测试。

协调核对最终JUnit为905 tests、0 failures/errors/skipped；报告另明确1个用户未提交live用例被排除。实施报告73451.27s的异常长计时及既有单项重核均原样保留，原因尚未从证据确定，不将其作为性能通过或用较短单项替代905项结果。旧820、889/1失败与其他诊断分别保留。

最新manifest的**56份证据SHA全部匹配**；wheel实际SHA与报告一致：`6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`。默认KnowledgeStore、合法知识命中/不可用gap、双角色同task/不同会话、撤权与匿名HTTP矩阵、移动端和浏览器重启/过时核查均有对应证据。已核验处理中断残留只停止本批归属已确认的进程，未全杀Python/PG或删除旧目录。

**结论：B4通过，G4已全部验收，可直接按用户授权新建B5独立会话。** 没有SSH、真实模型、预算变更或云端发布；G5和新双角色女声视频仍未完成。
