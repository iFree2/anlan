# P7-WP01：主链演示与接管排错实施计划

> 按 executing-plans 在当前目录执行；持续授权已覆盖常规设计，不另等确认。唯一代码写入者，保护用户未提交区。

**目标：** 一条固定离线命令重放材料补充、两类事件的工具/知识/候选/反馈/修订，以及冻结 Badcase 检查；交付可定位失败的手册和诚实证据。

**架构：** 新增 `scripts/takeover_demo.py`，顺序调用现有入口，不复制业务规则。材料循环与感知链分别使用独立合成任务；质量回放读取历史冻结输出，不将本次反馈自动标成新 Badcase。报告记录来源 SHA、逐步状态、前后 PG 账本和失败阶段。命令固定 scripted，无 live 参数、无模型凭据读取。

**取舍：** 仅手工命令容易漏验；另造全链应用会重复业务逻辑。采用薄编排器与人工讲解手册；HTTP/SSE 的现有清洁 wheel 演示单独说明，不把 CLI 回放冒称 HTTP 验证。

**技术：** Python 3.13、现有 PG17/BGE 缓存、subprocess、pytest。无依赖变更，无第二平台。

- [x] 冷启动：核对 AGENTS/Git/index、用户改动字节备份、PG即时账本及材料/PG最小 smoke；不读取模型凭据。
- [x] 写 `tests/test_takeover_demo.py`，先证明入口缺失；覆盖已有目录拒绝、子步骤失败/超时保留、质量缺输出不可计成功、账本不可用不报零或通过。
- [x] 实现固定五步骤：材料 PG demo → scripted perception → quality inspect → dev replay → holdout replay。独占创建输出目录；失败保存阶段与安全类别，停止依赖步骤；前后账本缺失记 unknown。证据 SHA 与当前源码前后指纹一致才通过。
- [x] 运行定向测试、真实主链演示；人为不可用 PG 的独立子进程验证失败留存，不停止项目 PG；验证重用路径被拒绝且原文件 SHA 不变。不复跑付费模型或并发失败刷分。
- [x] 写 `takeover-demo.md`、`troubleshooting.md`、`known-limitations.md`、`wp01-learning.md`；涵盖命令、预期输出、代码入口、恢复区别及4道本人题。
- [x] 更新 status/矩阵/验收/handoff，learning-log仅追加可逆入口与条目；验证用户原件逐字节保持，显式stage本包文件并提交；继续WP02官方文档及本地能力核对。

成功口径：脚本工程重放通过、PG预算不变、历史失败/未知根因保留。P6 CI434是历史基线；本包只报告本包实际验证数量。本人操作/讲解仍待用户证据。
