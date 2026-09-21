# P3阶段工程Gate：通过

2026-09-21。通过范围为PG用户偏好候选/生命周期、上下文筛选/预算、版本化指引、单Agent综合证据入口与同集消融工程链路。模型语义质量与本人掌握仍未通过，不能随工程状态升级。

| 验证 | 结果 | 原始证据 |
|---|---|---|
| 全量测试 | 228 passed，0失败/错误/跳过，118.35秒；34真实PG场景 | [pytest-final.xml](pytest-final.xml) |
| P3冻结工程Gate（python -O） | 8上下文场景、9同任务综合替身策略、24次CLI进程/7版Memory审计通过；预算21→21 | [gate-final.json](gate-final.json)、其关联review/memory报告 |
| 跨进程综合入口（python -O） | 陌生用户拒绝；已有PG任务和两项偏好在新进程读取，材料不变 | [cli.json](cli.json) |
| 原P2冻结工程回归（python -O） | 11/11，含实际Jaeger与真实本地编码；新增请求0 | [p2-regression-recheck.json](p2-regression-recheck.json) |
| 本包真实模型实验 | 3任务×3策略，9请求/20465token，应用接受6、拒绝3；没有重跑凑成功 | [live-report](live-report.md)、[原始输出](live-v1.json) |
| 静态校验 | ruff通过；未新增依赖，使用既有uv.lock | 最终运行记录 |

修复证据：缺少新模块、追踪状态字段缺失、综合遗漏显式知识问题、事实评分仅比reason导致假通过、事实追踪失败提示丢失、共享账本他人新增误计本实验，各有RED与GREEN XML。首版scripted9行结构通过仍漏知识问题，原报告保留，最终scripted/gate/live使用context-v2。

运行失败保留：WP02相关回归遇长约13小时的墙钟停顿，一项返回loop_timeout，单项和82项重跑通过，根因未证实。P2回归首次因未加载Jaeger Env在初始化停止，结果为ValueError且0场景；加载Env后11/11，不修改业务代码或冻结数据。原P2的PG非正常退出原因仍未确定。

数据集、知识/事实与指引摘要由`evals/phase03-regression-v1/manifest.json`冻结；输出工件用新路径，运行器记录摘要。Gate不依赖可被-O删除的assert，不调用真实模型。原P1/P2恢复、工具、知识、预占与追踪测试均包含在全量中。

单/多Agent后续对照基线是固定三工具采集＋一次模型综合，非P2自主选工具链；同任务使用相同材料revision、对象、as-of、知识库、偏好、输出合同和评分。不能以增加Agent数量、测试数或三例开发结果替代泛化、生产可靠性和个人掌握。
