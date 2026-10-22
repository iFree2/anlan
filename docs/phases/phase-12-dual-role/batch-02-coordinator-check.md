# P12 B2 协调检查（尚未验收）

日期：2026-10-23（Asia/Shanghai）。初始审查范围 `528de21..eb19aa4`，实现 `201b83a`、交接 `eb19aa4`。

## 初始独立回归

使用本地独立PG `anlan_p12_b2_20261022`，没有云端连接或真实模型调用。先运行dev-postgres Start/Env，并将两个项目DSN的数据库名替换为该本地测试库；没有打印DSN。命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_policy.py tests/test_collaboration_store.py tests/test_collaboration_service.py tests/test_collaboration_api.py tests/test_postgres.py tests/test_material_revisions.py tests/test_service_api.py tests/test_service_reliability.py tests/test_conversation_api.py tests/test_console.py tests/test_conversation_runtime.py tests/test_conversation_service.py tests/test_conversation_recovery.py tests/test_workflow.py tests/test_recovery.py tests/test_package_layout.py
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
```

结果：**268 passed in188.02s，0 skipped**；Ruff `All checks passed!`。这是修复前的定向回归，不代表下面的并发漏洞已被覆盖，不称全仓Gate通过。

## 审查发现与处置

按requesting-code-review进行只读审查，审查者未写文件、未运行测试。Critical无、Minor无，Important一项：notification identity ordinal分配顺序不保证跨task事务提交顺序。相同收件人T1先分配n并暂停；T2分配n+1先提交；收件箱推进到n+1后，T1稍后提交的n将永久漏读。

协调核对了 `CollaborationStore.append_event` 分配ordinal的位置、`CollaborationService.notifications` 的 `ordinal > after` 查询和当前task/request锁范围，风险路径成立。原事务保证“状态/通知一起提交”，不保证不同任务的消息按编号提交；两者不能混为同一个约束。

已在原B2会话发出范围内修复要求：真实PG可控并发RED复现、最小修复、回滚/不同收件人/重放语义回归、重新运行计划和相邻测试。先完成该修复，再验收和启动B3。当前未部署、未调用真实模型、未扩展为申请证据预核查或正式审批。
