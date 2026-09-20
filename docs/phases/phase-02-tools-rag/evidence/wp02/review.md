# WP02独立审查、复现与修复

2026-09-20。账本先做规格审查，再由另一审查者做代码质量审查，均通过。循环/HTTP同样先做规格再质量审查，发现并修复以下问题，均保留先失败的原始结果。

1. 整体超时在HTTP已预占/发出后取消，旧报告漏记当前attempt并写请求数0；现按last_attempt_id去重补录reserved_unknown，用量null，不退款。两个回合的超时替身复核记录[1,2]，与预占一致，保留已取得工具结果。
2. CLI在完成核验后附加读取预算快照失败，旧实现吞掉完整stdout；现保留证据，增加budget_warning=snapshot_unavailable，快照置null。上述两项红测见[retention-red.xml](retention-red.xml)，修复后26项[通过](retention-green.xml)。
3. 40,001字节深层JSON小于响应大小上限却触发RecursionError，绕过模型失败归档；工具网关及P1材料解析均补入invalid_output归类，使预占完成为failed。两路径红测见[deep-json-red.xml](deep-json-red.xml)，修复后37项[通过](deep-json-green.xml)。独立质量复核确认无剩余阻塞小样本联调的确定问题。

账本[30项测试](budget-green.xml)中7项真实PG场景，另含参数化输入边界；不能将30全算成PG。多连接/多进程竞争与预占后硬退出有实际证据；未直接制造并发finish或提交阶段断连，行锁与保守占用不等于生产SLA。测试使用随机test授权，没有消耗生产额度。

初次全量[138项](pytest-prelive.xml)通过之后，质量审查仍发现深JSON缺口；最终以pytest-final.xml为准，不用初次通过掩盖发现的问题。所有审查均未读取模型凭据或发真实请求。
