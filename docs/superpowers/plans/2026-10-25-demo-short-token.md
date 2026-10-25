# 合成演示短令牌 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户已批准最小改造，在当前会话串行执行，不创建worktree或实施子会话。

**Goal:** 按用户指定值修改两演示角色令牌，保留普通32位安全校验、原身份/业务/预算。

**Architecture:** TokenGrant显式默认关闭的demo_short_token，加ServiceConfig合成租户/角色/固定时钟门控；网页语法允许短输入但服务器仍认证。增量新wheel与私密配置原子替换，失败恢复原P12代码/配置，不动DB。

**Tech Stack:** Pydantic、FastAPI、原生JS、真实PG、现有pinned SSH部署桥。

## Task 1：测试先行与最小实现

负责 `tests/test_demo_short_tokens.py`、`src/anlan/interfaces/service_config.py`、`console/routes.py`、`console/assets/app.js`。

- [ ] 写配置RED：`ServiceConfig.model_validate({'schema_version':'local-service-v1','as_of':'2026-09-22T04:00:00Z','tokens':[{'token':'demo123','demo_short_token':True,'collaboration_role':'applicant','identity':{'tenant_id':'synthetic-short-login','user_id':'applicant'}}]})` 应通过；缺少演示标记、非synthetic租户、无角色、无固定时钟、非法字符/过短/重复令牌必须拒绝。普通32位grant应通过。HTTP使用新fixture和真实PG：两个GET info返回不同角色、401错误令牌、互读已有私聊404，不发messages。
- [ ] 运行 `.venv/Scripts/python.exe -m pytest -q tests/test_demo_short_tokens.py -m 'not postgres'`；确认因缺少功能失败而非环境错误。
- [ ] TokenGrant新增 `demo_short_token: bool = Field(default=False, strict=True)`，token字符校验按标记采用最少7或32；ServiceConfig after校验演示范围。info返回当前身份是否演示短令牌，网页connect语法最少7，模式提示短口令弱安全。不开放任何客户端授权接口。
- [ ] 本地PG17/loopback隔离库运行新测试及service/console/collaboration_config相邻回归；Ruff、wheel资源/离源码启动测试通过。明确排除live用例，保存准确结果。

## Task 2：发布与访问配置轮换

负责ignored `.runtime/p12-short-token-*` 运维脚本/私密输入/结果、新wheel，P12部署文档的追加记录。

- [ ] 构建新wheel、计算SHA；以原私密SSH+固定host key核对P12 current、无pending/预算、旧行摘要。仅使用服务器现有依赖，prepare新发布目录并验证wheel、配置。
- [ ] 0700/0600备份current路径与SHARED/console.json、PRIVATE/service.json和两份角色文件。指定口令只在ignored/私密文件传输，不入命令行/日志/Git。新配置恰好改两角色token及显式标记，身份/租户/profile/旧token全部保持。
- [ ] 验证新代码能读新配置后，短时停止服务，核对无pending和行快照；同一文件系统原子换配置与current再启动。异常恢复原P12发布和原配置；禁止旧P11写应用和DB恢复。
- [ ] GET检查新令牌两角色正确、旧两令牌401、匿名401、私聊隔离404、共享申请仍complete、旧行/预算91/21/6未变。校验新安装文件匹配wheel，公网JS包含更新。
- [ ] 下载两份新私密访问配置到新路径；把原本机两文件移到受限ignored备份路径，再换入新文件。实际浏览器验证手输及配置导入连接，不发业务messages。
- [ ] 只读代码审查、最终验证、提交自有代码/文档，不stage用户dirty路径。交付入口、更新后的配置及旧令牌失效说明；明确演示短口令风险，无新模型调用。
