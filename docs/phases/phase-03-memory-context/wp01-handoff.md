# P3-WP01：已通过，自动进入WP02

2026-09-21。同目录基线ef41080，未发现适用AGENTS，14文件32行中文注释与.idea保持未提交；未读取模型凭据、未发新请求。

实现：独立memory CLI、PG来源/当前状态/版本审计、两类枚举偏好、归属/时效校验和candidate→确认/拒绝→纠正/冲突→过期/删除。删除为不可恢复tombstone，source版本历史防止绕回。详见[计划](wp01-plan.md)与[ADR006](../../decisions/006-user-memory-lifecycle.md)。

验证：冷启动46项通过；[全量193项](evidence/wp01/pytest-final.xml)通过，含33真实PG测试。全量开始后另加跨来源回退负例，修复后[Memory专项9项](evidence/wp01/review-green.xml)通过（8真实PG）；ruff通过。最终测试集合194项，193全量＋新增专项覆盖，不伪造一次194全量运行。

[真实跨进程演示](evidence/wp01/smoke-initial.json)：python -O运行24条CLI命令、7个审计版本，归属拒绝/旧revision拒绝状态不变，跨进程active读取，冲突、过期、删除后列表为空，旧提议返回当前tombstone。每命令启动新Python进程，PG真实持久化。演示在最终跨来源修复前运行，修复由真实PG专项补验，不改写旧报告。生产账本前后均12/100，新请求0。

失败保留：[模块RED](evidence/wp01/red.xml)；[未消费旧来源回退RED](evidence/wp01/review-red.xml)；只读审查提出经过B来源绕回A/v1，AI在真实PG复现[watermark-red](evidence/wp01/watermark-red.xml)后改为全历史版本检查。审计后注入异常测试确认事务同时回滚当前状态和历史。只读审查的内存适配器复现与AI真实PG验证分开。

复现：先`scripts/dev-postgres.ps1 -Action Env`；`uv run python -O scripts/smoke_memory.py --output .runtime/memory-new.json`（输出须不存在）；`uv run pytest tests/test_memory.py -q`。固定时钟2026-09-21T00:00Z，反馈到2026-10-21T00:00Z过期，不修改冻结日期。

下一包[WP02计划](wp02-plan.md)：纯上下文组装、可解释裁剪及可信包号配置；随后WP03做版本化业务指引/单Agent综合基线和同集消融。单键单候选、模拟身份、保留合成审计均属限制，不宣称生产隐私删除。P2无混合收益、次要摘要主张引用不足、PG异常退出原因未明继续保留。个人掌握待本人证据。
