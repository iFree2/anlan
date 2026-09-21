# ADR006：用户呈现偏好的候选与生命周期

2026-09-21，P3-WP01。采用既有PG中的三个小表，不引入Memory框架。`memory_feedback`保存归属由模拟入口注入的版本化SYNTHETIC反馈；`memories`每用户每键一条当前状态；`memory_revisions`保存不可变合成审计。不是checkpoint、实时事实、企业制度或权限授权。

只允许详略和呈现顺序的枚举值。source_ref/version必须先登记，hash由宿主计算；内容同版本不可覆盖，候选仅复制已登记且有效的来源。来源未找到与越权统一拒绝。没有自由文本记忆、模型直接写入或自动确认；Codex长期编码授权不进入业务数据。

确认、拒绝、显式冲突、修正、过期和删除使用expected_revision。每次连接事务持有行锁；首次提议用用户/键advisory事务锁处理无行竞态。当前状态与审计同事务；故障整体回滚。修正回到candidate等待确认；冲突停止active读取。历史中已经使用过的来源和较旧来源版本不得通过更换来源绕回；新反馈明确登记新版才可纠正。

读取同时约束tenant/user、active、updated_at<=as_of<expires_at，故过期立即不可检索，不依赖expire命令或后台任务。expire只用于显式状态审计。写时钟不得倒退；模拟as_of用于复現，不是生产任意时间穿越权限。普通列表不返回候选或审计。

重复提议同一来源返回当前状态，不返回缓存的旧候选；不同来源冲突不覆盖。删除为永久tombstone，当前小实现不提供撤销/恢复；show/history仍可由本人读取合成记录。这不是生产隐私删除或隐私合规承诺。候选只有一条，来源登记也不证明真实用户意图；本地CLI身份是模拟，未来服务端认证需单独实现。

独立入口 `uv run python -m anlan.memory_cli`；无需模型、向量或Graph迁移。实现与负例见[P3-WP01计划](../phases/phase-03-memory-context/wp01-plan.md)和[evidence](../phases/phase-03-memory-context/evidence/wp01/)。
