# B2 RED / GREEN 过程记录

2026-10-27。所有 PG 用例使用项目 PG17 loopback 隔离库 `anlan_p13_b2_20261027`；不含连接串或密码。测试使用真实 registry/checkpoint、FactTools 与 PG KnowledgeStore；知识检索的向量由测试专用 UnitEmbeddings 提供，未调用供应商模型。

## 实际观察到的 RED

- 初次 evaluator 收集：`ModuleNotFoundError: anlan.preflight.evaluator`；最小实现后 2 passed。补“来源有效期未知”用例：1 failed / 2 passed，失败为 ready=True；修复后 3 passed。
- 真实 PG job RED：先遇到本地服务未启动及指定库不存在（这两次仅为环境失败，不计能力 RED），启动并创建隔离库后，实际任务/绑定 fixture 下出现 `PrecheckStore has no attribute enqueue`；实现后 job 与 evaluator 组合 4 passed。
- 完成门控第一轮 RED：旧实现可在没有 check 的情况下完成，`DID NOT RAISE InvalidTransition`。扩展冻结字段/无绑定提交/同事务回滚的 RED 为 3 failed，分别是新字段被拒绝及缺绑定没有拒绝。
- 不可变 job 输入 RED：1 failed / 13 passed；SQL020 尚允许改写 input_snapshot。加入数据库触发器后原断言通过。
- 旧轮次晚回写 RED：`KeyError: stale`；已有新 recheck 时，旧轮次尚未明确记 stale。加入最新 job ordinal 比较后通过。
- evaluator 查询身份 RED：1 failed / 3 passed；错误 tool 名仍可 ready。加入查询身份校验后通过。
- evaluator not_applicable RED：1 failed / 4 passed；ok transport outcome 掩盖了业务 reason。显式拒绝非空 reason 后通过。
- 重查完整载荷 RED：仅把相同 request_id 的 reason 增加尾随空格未冲突，1 failed / 1 passed；改为保留原始非空 reason 后修复。
- 最终集成首轮：162 passed / 4 failed，见 `regression-initial.xml`。其中一项是旧组合按实际权限返回 AccessDenied，而测试仅期待 InvalidTransition；另外三项揭示后台任务锁竞争及占用未主动释放租约。
- 针对租约竞争新增真实 PG RED：`contention-red.xml`，1 failed / 12 deselected；持有实际 registry 锁后，worker 返回但 job 在锁释放后仍不可领取。修复后 `contention-green.xml` 为 1 passed / 12 deselected。相关协作重放、完成竞争、收件箱提交顺序专项 5 passed / 15 deselected。
- 第二轮完整组合为 166 passed / 1 failed，见 `regression-material-contention.xml`：旧材料 HTTP 修改遇后台短任务锁而立即 409。新增固定持有真实 registry 锁的 `material-lock-red.xml`（1 failed / 13 deselected），API 对读取/修改/恢复仅重试 TaskBusy 后，`material-lock-green.xml` 为 1 passed / 13 deselected。业务版本、阶段冲突仍不重试，材料 operation 的幂等/恢复合同保持。

## 验证纪律

最终完整组合为 **170 passed / 0 failure / 0 error / 0 skipped**，375.27s，见 `regression-green.xml`。`policy-preservation-green.xml` 是收尾加强 B1 原有“完成后保持 required”断言的复验，1 passed / 12 deselected，不与主组合相加。全目录 Ruff 结果为空数组；最终 wheel 以 `wheel-layout-release.json` 为准。

`regression-green.xml` 记录最终指定组合；`source-lock-green.xml` 单独记录实际 PG 来源行锁测试，不与主组合重复计数。两个实际新进程用例分别恢复 queued，以及领取后 `os._exit(47)` 的 running job；后者通过测试明确令 PG lease 到期，再由新进程留下 expired/completed 两条尝试历史。

旧 P12 fixture 显式确认绑定、读取真实三项查询结果并选择引用；没有关闭 required 策略。旧聊天卡片冻结空引用，确认受控 409，再由显式结构化完成命令选择引用。没有运行用户未提交的 `tests/test_tool_loop_live.py`、SSH、真实模型请求或额度重置。
