# 工程基础增量 ECS 发布记录

2026-11-22 已将工具执行、知识 v2、统一评测与动态 MCP 基础代码发布到既有阿里云 ECS。当前运行 release 为 `/opt/anlan2/releases/engineering-20261119`，公网入口仍是 `http://47.93.218.52/anlan/console`。

- 应用提交：`57c7c8b16d6d6102c44884ba7e777c65cc4799fc`，父提交为已上线业务问答 `ae235009d729a58969d560ee375a872d2c13e210`。
- 发布操作提交：`90149625fcd676e48addd76981fc469d535017d6`。
- wheel SHA-256：`9b8f72e5d26b58d3f40af1d797b8d455952fce728d2c655218a3d93c44b2d901`；187个应用文件与应用提交逐字节匹配。
- 数据库备份 SHA-256：`0e7acd8b850aa2c508837845c2ee48978000caf6aa00638aaabf3b60ab71f6ed`。
- 当前服务 PID：`4107178`；服务、公开health和console均为200，匿名info为401，legacy/applicant/safety_manager三身份readiness通过。
- SQL迁移集合保持 `[1,5,6,7,8,9,13,15,16,17,18,19,20,21]`；022/023未应用，没有注册、启用或调用生产MCP。
- 模型历史尝试保持146，本次0次模型请求。六类执行中操作/消息/核查/预算/precheck job/attempt均为0。

## 发布门禁与验证

当前整合代码先运行完整非live回归：1673 passed、1 live deselected、1第三方警告，源码指纹426项未变。发布helper采用TDD，42项失败注入测试通过，独立release_review重跑42项及Ruff通过并关闭配置漂移和forward恢复快照两项Important。

prepare前后核对当前release、全部pending、配置/环境/systemd指纹、迁移、三身份、关键依赖实装版本及所有旧行/模型账本。备份包含数据库、console.json、app.env、systemd与恢复策略，备份后候选154模块在目标venv离线导入；合成TXT probe确认草稿保持未发布，MCP Schema仅验证模块机制。

激活验收为零业务写入：回读既有业务问答四类历史及三身份私聊隔离、双方共享申请读取、审核人owner-only历史404；没有创建新对话、消息、route或查询审计。发布前后全部业务表数量/逐行摘要、账本/packages/statuses、配置和系统指纹一致。

线上只安装工程代码。MCP管理员策略、真实企业服务、SQL022/023与普通用户动态入口均未启用；不能把模块可导入表述为企业MCP已接入。知识语料仍是既有合成环境，没有发布公开候选或真实法规。

## 恢复与边界

发布helper为 `/opt/anlan2/release-engineering-20261119.py`。`rollback`进入既有维护应用，确认维护503且业务静默后保存独立当前数据恢复快照；`forward`以该维护快照为基线恢复当前工程版，允许保留发布后合法业务与审计，不恢复旧数据库、不降权限或擦除记录。维护切换或快照失败明确返回recovery_failed。

配置、环境和systemd指纹在prepare入口、备份后、导入后、激活入口及停服后切换前重复核对；中途漂移直接拒绝。helper与候选制品使用固定SHA；远端业务问答helper和本地副本只存在CRLF/LF差异，按远端原始字节SHA固定。

本轮没有真实模型质量、真实企业系统、生产TLS/SSO、多人现场或正式审批验证。人员/作业票MCP、多来源/分页、普通对话装配、真实文档治理与领域人工评测仍是后续工作。
