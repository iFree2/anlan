# P2-WP02交接：有界模型工具循环与共享请求预算

日期：2026-09-20。工程包通过，P2阶段继续进入示例知识摄取/检索；个人掌握独立待验。继续按roadmap长期授权自动推进，不等待常规确认。

## 交付

新增`check-facts-agent`，默认明确的scripted协议替身，`--mode deepseek`为真实模型。模型在两个只读工具中选择动作，代码校验白名单、参数和输入业务引用，工具再检查可信身份的对象权限；观察按原call_id反馈。最多3个模型回合、4次工具动作、75秒总时限，非法动作/重复ID/超预算/失败有显式终止原因。查询结果与最终摘要分开，摘要要求引用观察且标记unverified_candidate，不改P1材料或审批状态。

生产账本位于现有项目PG：`model_budget_authorizations/model_budget_attempts`，授权ID固定`20260920-long-term-v1`，每包10/新授权后累计100。事务提交预占后才发送HTTP；失败/硬退出/未知记录仍计数，不退款、不复用发送许可。旧材料模型入口也要求该账本，进程3次上限不再是唯一限制。`budget-status`只读查询，不发模型请求；测试使用独立授权。

`tool_model.py`定义动作/摘要合同与供应商适配，`tool_loop.py`控制动作/观察/停止，`model_gateway.py`约束输入32KiB/响应64KiB和HTTP预占，`budget.py`与SQL002负责持久计数，`live.py`集中生产授权入口。详细决定见[ADR003](../../decisions/003-model-budget-and-tool-loop.md)。

## 验证

- [最终全量](evidence/wp02/pytest-final.xml)：140 passed，0失败/错误/跳过，237.20秒；含20个真实PG场景（原11、CLI2、账本7）。ruff通过。
- 启动补充检查：`anlan db-init`同时准备预算表且保留已有6次预占；旧评测入口在打开输出前初始化账本，并使用Windows selector事件循环。相关evaluation/CLI/facts-CLI 8项再次通过，ruff通过。
- [冻结P1回归](evidence/wp02/p1-regression.json)：8例25步通过，历史预测重评分保持相符，无P1真实模型重跑。
- [协议替身3任务](evidence/wp02/scripted-final.json)：动作/观察/停止均符合口径；这是替身，不是模型效果对照。
- [真实3任务](evidence/wp02/live-v1.json) / [逐例复核](evidence/wp02/live-report.md)：正常、过期、无记录加材料注入。各2次请求，6次/7283token，动作与工具观察均符合此已见集合；摘要未自动语义评分，AI复核不等于独立或本人验收。
- [审查记录](evidence/wp02/review.md)：整体超时漏记预占、预算快照吞结果、深层JSON绕过归档三项问题，均先红后修复，旧失败证据保留。

本包用量：6/10，新授权累计6/100；输入6342、输出941、总7283token，usage完整，实扣未知。唯一账本[后快照](evidence/wp02/budget-after-live.json)全部succeeded、无reserved。P1历史3次/1184token单列，不加到新授权余额。没有新增供应商/模型价位或隐式重试。

## 运行与边界

先加载PG环境；`uv run anlan start`取得task，然后`uv run anlan check-facts-agent --task <task> --refs-file examples/synthetic/fact-refs.json --as-of 2026-09-20T12:00:00Z`离线演示。省略as-of用真实UTC，示例到期返回unknown符合预期。真实模式需已安全配置环境，重复实验占额度，查看已有结果无需再次调用。

PG账本不是供应商金额限制或exactly-once。DB管理员能篡改，恢复旧备份前必须核对审计快照与实际用量。快照失败保留事实报告并发出警告，不能据缺失快照推断未占额度；取消时未知用量保持null。身份为本地模拟，材料或知识不提供授权。

当前尚无pgvector/知识摄取/检索对照/平台追踪。下一包P2-WP03优先建立版本化示例知识、租户/有效期/撤回过滤与真实pgvector查询；本机未发现Visual Studio C++、Docker或WSL，先核实可复现的用户目录安装方法，不改系统PG10。平台追踪另用后续小包接入，阶段Gate仍未通过。
