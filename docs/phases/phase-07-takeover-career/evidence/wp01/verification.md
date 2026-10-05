# P7-WP01工程验证

2026-09-28启动，按用户要求暂停；2026-10-05明确恢复后完成余项。HEAD基线fde18db，用户未提交译文与学习排序保留。

- 冷启动23项通过；原入口/质量定向17项通过。原demo-v1五步骤passed，42→42；10月5日检查其源码和工件摘要均未变，用户17个原脏文件字节均一致，index空。PG当时已停，仅启动项目PG17；停库原因未知，系统PG10未改。resume-budget-20261005.json仍42/100、40成功/2失败/0reserved。
- 恢复smoke18项通过。不可用端口故障：退出1，budget_before失败，快照/增量unknown且未执行子步骤；既有目录退出2且原报告SHA不变。见fault-checks-v1.json和unavailable-v1，项目PG未停。
- 初始red.xml六失败证明缺入口；green.xml17通过。独立审查发现超时孙进程遗留、PYTHONPATH执行来源不绑定；review-red.xml两项真实文件/进程反例复现。用Job Object＋启动屏障和源码绑定修正。首修CreateJobObject的None名称TypeError保留于review-green.xml，改为匿名空名称后review-green-v2.xml八通过。
- final-tests.xml：23 passed、0 skipped，含12项入口/失败路径与11项质量合同检查；ruff定向通过。进程测试无PG/模型副作用。未重跑P6全量434或并发失败刷分。
- demo-v2是修订后的实际完整运行，五段通过：材料9命令/3revision，两类真实PG/BGE＋scripted感知链，inspect11记录，开发6匹配（仅4个输出可回放，另2不可回放），已见合同留出5匹配。来源前后指纹相同，账本42→42，零新增模型请求；工件SHA记录于report.json。
- 独立只读复审确认两项阻塞已解决，无新增阻塞；未代替实际测试。其非阻塞建议为增加孙进程启动握手及正常父退出清理专测；本次以真实红绿反例与完整demo记录清理能力，不声称所有平台已验证。

Q-P6-001/002继续开放，个人掌握未提供。P6历史CI/wheel/HTTP仍为历史证据，本包不称新HTTP或真实模型效果通过。新学习条目另存wp01-learning.md，learning-log整文件不stage。
