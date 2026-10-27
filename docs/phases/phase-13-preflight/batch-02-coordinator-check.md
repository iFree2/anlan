# P13 B2 协调独立验收

协调验收日期2026-10-28。实现449dd214d74380b62ab4649de6598c6087ec5fe6，执行失败投影修复2d47a447cbc56ce2978212d12792b8bde7166928；基线c390d72。只验本批后台/服务层，不代表UI、事件对象复用或全部P13完成。

## 独立复验与制品

协调建立新的本地loopback PG17隔离库 `anlan_p13_coord_b2_20261027` 并显式启用vector，未复用实施库、连接ECS或调用供应商。DSN仅在进程环境使用，不写入报告。

实现基线449dd21实际运行：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_preflight_evaluator.py tests/test_preflight_jobs.py tests/test_preflight_service.py tests/test_preflight_gate.py tests/test_collaboration_api.py tests/test_conversation_api.py tests/test_audit_only_budget.py -m 'not live_model' --junitxml=.runtime/p13-b2-coordinator.xml
```

**49 passed，0 failures/errors/skipped，84.45s**，全目录Ruff通过。包含实际FactTools/PG KnowledgeStore、两个真实新进程queued/running恢复、lease fencing、同事务/重复提交/回滚、源变更/知识行锁、旧卡片与旧组合门控、audit_only保持。知识向量在这些合同测试中使用UnitEmbeddings，不能冒充神经检索质量或真实模型验收。

修复2d47a44后，为新的inputs_current分支和失败投影复验：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_preflight_service.py tests/test_preflight_gate.py -m 'not live_model' --junitxml=.runtime/p13-b2-coordinator-final.xml
.venv/Scripts/python.exe -m ruff check src tests evals scripts deploy
```

**30 passed，0 failures/errors/skipped，62.28s**，Ruff通过。49与30有重复覆盖，不相加；实施主组合170项是449dd21的记录，修复后的65项相邻回归亦单独记录，均不充当B4全仓Gate。

原release wheel c785f33c...仅对应449dd21，实施已明确没有将其当成修复后制品。协调重新构建 `.runtime/p13-b2-reviewed-dist/anlan-0.1.0-py3-none-any.whl`，SHA256 **a0a8345d36a1e1f7c63549e204c4f0a5839f0d385567596f5e7723de41326ef4**。以新输出 `.runtime/p13-b2-reviewed-package.json` 执行verify_package_layout：107模块离源码导入、20资源、9CLI通过，包含SQL020；没有覆盖实施报告。独立JUnit及包报告附于evidence/b2-coordinator。

## 审查结论

独立只读审查未发现Critical/Important，发现一个Minor：来源执行异常缺少有效期，导致输入没变也显示stale。协调核对实际代码并交回原B2会话；不并行改实现。

原会话先用真实PG复现两种输入状态，再引入execution_status=failed和独立inputs_current。失败始终current=false、ready=false，没有补造valid_until，异常文本/trace不进入共享投影。输入变化才独立stale，显式重查保留旧失败与尝试。最终源码复核无剩余Critical/Important/Minor，协调的修复后30项复验通过；不宣称审查者执行了测试。

## 已满足与后续

提交/重提与唯一自动job同事务，进程循环可恢复；三查询使用当前绑定和作业相关问题。查询outcome与active/normal/当前引用分开评估，完成操作核对材料/绑定/check/来源/时效和人工选定引用。缺口可继续补充、源修复可重查和重提。两个不同绑定实际查询worker-b/area-b，不借用固定profile。源文件哈希与PG不能构成跨系统原子提交，现阶段限制已在交接说明；知识行锁与完成事务竞争已实测。

G1剩余后台查询/结果授权与G2服务层通过；UI/对话引用选择、接口路由、事件binding版本及双浏览器交互由B3验收。当前普通聊天候选不能代替人选择引用，B3必须提供结构化选择并冻结，不得用模型文字填充。

本轮无真实模型/SSH/部署/令牌或限额变更，保留所有原dirty路径。B3可启动。
