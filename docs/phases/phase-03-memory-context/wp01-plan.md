# P3-WP01 实施设计与步骤

2026-09-21；沿用已授权范围，同目录串行执行。采用 writing-plans / executing-plans / TDD；不增加常规确认门槛。

目标：将版本化 SYNTHETIC 结构化反馈转换为本用户的呈现偏好候选，真实 PG 保存来源、版本和完整生命周期。

选择：单键单行状态＋不可变版本审计＋独立反馈来源表。比 checkpoint 内嵌更清楚地区分跨会话偏好；比通用多候选平台更小。白名单只有 `detail_level=brief|detailed`、`presentation_order=unknowns_first|sources_first`。反馈包含显式 SYNTHETIC 标签、source_ref/version、key/value、observed_at/expires_at；归属由模拟可信入口注入。摘要、事实、批准和自由文本指令一律不能成为记忆值。

候选的值只能复制已登记、同用户、时间有效的来源，hash由服务计算。同 source_ref/version 不同内容拒绝。每用户每键只有一个 memory_id；新提议若已存在不同来源就返回冲突而不覆盖。相同来源重复提交只返回当前状态，不复活旧候选。

状态路径：candidate→active/rejected；candidate/active/conflicted→correct→candidate；active→conflicted（显式标记，停止读取）；非终态→expired；任意非deleted→deleted。correct须指定新的有效反馈和expected_revision；rejected/expired允许显式correct，deleted为永久tombstone（首包不支持撤销删除）。每次写入锁定记录、检查revision和非倒退时钟、事务写当前值及审计。读取仅active且创建时间不晚于as_of、到期时间晚于as_of；过期不依赖后台清理，expire命令保存显式审计。

文件与步骤：

- [x] `tests/test_memory.py`：先写模块缺失、白名单、不可变来源、隔离、过期、revision、冲突、删除重放、并发确认的失败测试，运行并保存RED。
- [x] `src/anlan/memory.py`、`sql/004_memory.sql`：实现来源与记忆事务、时间检查、状态转换；运行真实PG测试保存GREEN。
- [x] `src/anlan/memory_cli.py`：独立 `python -m anlan.memory_cli`（避免继续扩大主CLI），提供init/feedback/propose/list/show/history/confirm/reject/conflict/correct/expire/delete；每命令为新进程，模型配置完全不参与。
- [x] `examples/synthetic/memory/feedback-v1.json`、`scripts/smoke_memory.py`：固定合成来源；运行跨进程全路径及错误不变验证，`python -O`下显式检查。
- [x] 自审边界/故障、原P1/P2关键回归与全量测试；保留失败和原始JSON/XML。更新ADR、架构、status、验收、矩阵、learning-log、handoff；只提交本包文件与改动，然后自动进入WP02。

验证命令（先加载项目PG Env）：`uv run pytest tests/test_memory.py -q`；`uv run python -O scripts/smoke_memory.py --output docs/phases/phase-03-memory-context/evidence/wp01/smoke.json`；`uv run pytest -q`；`uv run ruff check .`。测试使用随机租户，生产模型账本只读核对；新增真实模型请求必须为0。

失败语义：来源不存在/越权统一拒绝；任何验证或事务故障不提交记忆/审计。时钟仅在本地复現注入；无生产认证、无生产隐私合规声明。记录已知限制：每键仅一个候选，删除不可恢复；审计保留合成值；学习掌握待本人证据。
