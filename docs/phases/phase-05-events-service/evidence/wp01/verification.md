# P5-WP01：通过

2026-09-22，基线ebbdcfb。本包仅合成事件接收/关联，无模型凭据读取或模型请求；阶段P5尚未通过Gate。

| 验证 | 结果 |
|---|---|
| 冷启动 | PG17.11运行，22项材料恢复/包结构/真实PG smoke通过 |
| 全量测试 | [pytest-final.xml](pytest-final.xml)：341 passed、0 skipped，包含54真实PG；另有[evaluation-validation.xml](evaluation-validation.xml) 1项报告验真，总342项 |
| 事件测试 | [events-final.xml](events-final.xml)：42通过，含接收/幂等/水位/时效/身份/材料版本/合同/未完成提交/实际终止关联连接/CLI |
| 两类独立进程回放 | [replay-v1.json](replay-v1.json)：2类型×6命令，共12进程，原始报警active、材料不变；同ID重放不再次处理 |
| 旧P4冻结回归 | [p4-regression.json](p4-regression.json)：9串并行、6单双角色、3真实Java/MCP、2CLI、61故障全部通过 |
| 预算 | 事件回放与P4回归都30→30，唯一PG账本未变；P1历史另列 |
| wheel | [wheel-final.json](wheel-final.json)：离源码全部模块导入、6资源字节、7新旧CLI；uv build/ruff/uv lock --check通过 |
| 代码审查 | 独立AI只读审查未发现实质问题；建议的连接终止/材料pending/合同/run覆盖已补并由本任务亲自运行。不是本人掌握或人工金标 |

失败原件保留：contracts-red.xml、storage-red.xml为缺模块收集失败；增加空接口后contracts-red-behavior.xml的22红测、storage-red-behavior.xml的15红测证明缺行为；cli-red.xml为缺CLI失败。wheel-initial.json失败根因为旧校验器固定5资源，新SQL实际正确打包为第6资源；已修校验并加事件CLI验证。两处ruff格式问题已修正。未隐藏或改写早先P2/P3/P4的失败与SHA。

数据库实例没有停启，验证的是独立客户端进程/连接恢复；连接终止只针对测试创建的本次关联连接，不动用户chat、系统PG10或共享PG实例。原始记录仅保证应用路径不可改，数据库管理员仍可改库；本地identity/binding是合成宿主配置，不是生产认证。

本包不评测视觉/传感器识别质量，不做风险模型或报警处置；`linked`只表示processed_at时点的材料版本关联。WP02才能实现候选当前性、材料显式revise和人工反馈；个人掌握仍待本人证据。
