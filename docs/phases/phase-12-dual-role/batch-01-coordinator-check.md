# P12 B1 协调验收

日期：2026-10-22（Asia/Shanghai）。审查范围 `1fe1dec..2f18764`，实现提交 `6854844`，实施交接提交 `2f18764`。本页由总协调会话记录，不替代实施会话的RED/GREEN交接。

## 独立实跑

```powershell
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL -replace '/anlan_dev$', '/anlan_p12_b1_20261022'
$env:ANLAN_DATABASE_URL = $env:ANLAN_TEST_DATABASE_URL
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_config.py tests/test_collaboration_policy.py tests/test_collaboration_store.py tests/test_conversation_store.py tests/test_service_api.py tests/test_package_layout.py
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
```

协调实跑：**186 passed in 45.39s，0 skipped**；随后Ruff：`All checks passed!`。使用已创建的本地独立PG测试库，未访问云端或调用真实模型。此为六文件定向回归，不声称全仓测试通过，也不把实施与协调同一套测试相加。

## 只读审查与包产物复核

按requesting-code-review技能派发只读审查，审查者完整阅读已确认设计/计划B1/交接及实际diff、源码和新增测试；未运行测试、未修改文件。结果：Critical/Important/Minor均无提出项，未发现B1阻塞。

协调另核对既有wheel报告 `status=completed`、17份资源、9个兼容命令且返回码全为0；实际wheel SHA-256与报告一致：`aa98dfd1aa1011b50f5e101d7d340f04f8d6eb4e0bd5c422966035612cb0c944`。这里是报告/文件哈希核对，不声称协调再次运行了离源码命令。

配置角色缺省None、相同身份矛盾角色拒绝；策略验证租户/明确参与关系/角色/阶段；ensure_draft先验证原registry owner，并发注册保持已有阶段和原任务数据。SQL017不改旧任务、预算或SQL012；所有实际提交路径均属于B1或必要包校验回归。原用户dirty路径仍保留。

## 结论与B2边界

B1可进入B2，尚未实现跨角色业务命令、HTTP/Graph接入、前端双会话、线上部署或视频。

B2必须扩展store支持同连接事务，复用原task session advisory lock，在锁内核对checkpoint/pending与双版本；状态/事件/通知/回执同事务。保持真实actor与storage_scope分离；旧HTTP/Graph材料入口也必须执行协作冻结。通知需按当前配置角色和参与关系再次授权，不把recipient FK当成完整权限检查。
