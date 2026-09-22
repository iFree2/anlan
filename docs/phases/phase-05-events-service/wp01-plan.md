# P5-WP01：模拟事件原始记录与可信关联

2026-09-22。采用既有持续授权，原目录内执行；不需要模型或凭据。冷启动HEAD ebbdcfb，22项最小smoke通过，PG17.11运行；未发现适用AGENTS。用户16路径译文及.idea保持未提交。

**目标**：两类SYNTHETIC报警持久化、幂等/乱序保护、可信宿主绑定与当前材料核对，可跨进程恢复关联。

**方案选择**：采用独立原始事件表＋来源水位＋一次关联结果。直接写Graph会把报警存活依赖Agent；引入MQ/IoT平台没有当前并发规模证据。此包不改Graph/resume。纯合同在workflows/event_contracts.py，PG存储在infrastructure/events.py，关联规则在workflows/events.py，锁与Saver装配在interfaces/event_runtime.py，薄CLI在interfaces/events_cli.py。

## 合同和状态

- 事件正文仅schema_version/data_origin/event_id/sequence/kind/object_ref/observed_at/expires_at/alarm_state与两类测量字段。禁额外身份、任务、控制字段；时间须带时区，数字有限且有界。报警state仅active；这里记录上游模拟报警，不制定生产阈值。
- identity/source_id来自宿主入口。宿主SourceBinding包含identity/source_id/kind/object_ref、唯一task_id、material revision/run、有效时窗；这是显式模拟关联声明，不声称从材料自然语言可靠推断对象。配置非空且身份匹配才有权关联，未知来源留原始记录与unknown_source。
- 原事件首事务提交，不调用Agent。事件键为tenant/user/source/event_id；同键同正文返回现有记录，内容冲突拒绝。可信binding快照保存在首次接收行，重放不能换配置改归属。
- 水位按tenant/user/source串行，序号必须严格增加且observed_at不倒退；不同event_id复用序号、过期/未来/错误对象保留明确原因，不覆盖当前。过期为接收时判断，后续关联还检查当前时间。跨来源无全局序号。
- 合法接收为pending；关联后linked或明确拒绝。处理在归属校验之后读取checkpoint；任务锁、Saver读与结果提交同一专用PG连接。关联期间丢连接不能借另一连接写结果。锁忙/进程退出保留pending，重试可恢复；一次处理结果不可覆盖。
- 关联同时检查合同、无pending材料操作、材料revision/run、事件仍是本来源水位与时效。未知任务/越权统一task_unavailable，不泄漏别人的材料。旧结果仅表示当时关联快照，读取当前性另算，永不代表批准或实时事实。
- 所有原始报警保留active；没有解除报警、批准或控制命令接口。WP02另定义重核版本，不能把awaiting_review偷换成waiting_input。

## 执行步骤

- [x] 1. `tests/test_events.py`先写合同拒绝、两类载荷与绑定纯规则测试，运行红测，再实现合同。
- [x] 2. `tests/test_events_postgres.py`先写真实PG接收/去重冲突/水位、跨身份/错误任务/版本/并发/关联崩溃恢复，运行红测，再实现SQL005、存储、规则与运行时。
- [x] 3. 增加CLI和独立冻结回放，两个新进程接收/读取/恢复；产生新的事件时段与来源，历史P2/P3/P4冻结数据不修改。
- [x] 4. 全量pytest（加载真实PG环境、零skip）、ruff、P4原冻结Gate验证核心回归；保存每轮失败及最终结果。
- [x] 5. 更新acceptance/status/矩阵/learning/handoff，核对译文及历史文件保留，单独提交WP01，然后推进WP02。

测试命令：`scripts/dev-postgres.ps1 -Action Env; .venv/Scripts/python.exe -m pytest tests/test_events.py tests/test_events_postgres.py -q --junitxml=docs/phases/phase-05-events-service/evidence/wp01/<新名称>.xml`。初次应因缺实现失败，完成后全部通过；PG未配置为失败，不将skip算通过。逐项测试实现作为可执行计划，不复制第二份易漂移代码。
