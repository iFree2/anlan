# P13 B1 协调独立验收

2026-10-26。实现/交接提交 `8d552e100d83e348540aae0fe6d0937baa7c09e2`，基线6acdf09（期间协调ffcd1d1只改设计/进度文档）。本批不是整个P13完成。

## 独立执行

协调使用项目本地PG17 loopback的新库 `anlan_p13_coord_b1_20261026`，不复用实施测试库、不连接ECS，凭据只在进程中处理。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_preflight_contracts.py tests/test_preflight_catalog.py tests/test_preflight_bindings.py tests/test_preflight_store.py tests/test_collaboration_config.py -m 'not live_model' --junitxml=.runtime/p13-b1-coordinator.xml
.venv/Scripts/python.exe -m ruff check src tests evals scripts deploy
```

实际 **69 passed / 0 skipped / 0 failures，28.89s**，Ruff通过。包括目录/ACL、严格资源合同、真实checkpoint/owner、双版本/阶段冻结、撤权重放、跨task request命名空间与等待锁、回执前失败回滚、重复初始化、不可变SQL历史及旧数据保持。没有模型调用或SSH。

实施最终105项回归与协调69项分开记录，不相加；原全仓旧Gate不能替代本批。实施wheel实际SHA为 `3cce263e2d075e7f91f849ae11e6472b7537ae78dcd45863ae9c1523a9bd06bb`，协调重新计算一致；资源/离源码验证原证据为103modules/19resources/9CLI，协调另以新输出路径复验，不覆盖原报告。

## 审查与修复

只读审查提前发现SQL019的CREATE OR REPLACE TRIGGER不兼容现有云端PG13.23；协调核对原代码后交回原B1会话，未自行并行改源码。依据[PG13语法](https://www.postgresql.org/docs/13/sql-createtrigger.html)与[PG14语法](https://www.postgresql.org/docs/14/sql-createtrigger.html)核对。

实施完成针对性RED，改为同一初始化advisory锁/事务内DROP TRIGGER IF EXISTS＋CREATE TRIGGER，重复初始化和两表UPDATE/DELETE保护在PG17通过。最终commit复核已关闭该Important；无剩余Critical/Important/Minor。这里是PG13语法兼容审查，不声称实际运行PG13。

## 结论与后续边界

B1验收通过：可信目录、角色/对象权限、版本化绑定与PG存储底座已完成。G1涉及实际跨对象工具查询及预核查结果授权的两项仍保持未勾选，分别待B2/B3补验；HTTP/浏览器集成亦待B3。

B1没有接HTTP/UI、自动工具查询、来源当前性或完成门控，也没有云端发布。B2需要读本交接实际BindingService/PrecheckStore接口，接持久化job/结果、提交自动触发和完成门控；不得将B1绑定确认测试说成三项事实/知识已核查。

保留用户dirty路径，未git add -A，无worktree、付费请求、额度政策或角色令牌变更。
