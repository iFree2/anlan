# P12 B4 协调检查（尚未验收）

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
