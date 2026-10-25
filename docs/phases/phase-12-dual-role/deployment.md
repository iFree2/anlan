# P12 阿里云双角色部署与视频

日期：2026-10-25（Asia/Shanghai）。本期只到材料核查完成；不提供正式审批、开工授权或真实设备监控。

## 入口与身份

入口：[安澜控制台](http://47.93.218.52/anlan/console)。使用两个独立浏览器上下文，分别选择本机 ignored 私密文件：

- 申请人：`D:\src\agent学习\安澜2.0\.runtime\p12-b5-access\applicant.json`
- 安全人员：`D:\src\agent学习\安澜2.0\.runtime\p12-b5-access\safety-manager.json`

这两份文件仅用于本人演示身份连接，不应公开分发、提交 Git 或展示令牌。浏览器只在当前页面内存保存凭据，刷新后重新选择。服务器共同配置为 `/opt/anlan2/shared/console.json`，两份新增角色配置原件在 `/opt/anlan2/shared/p12-collaboration-20261025/`；未把服务器 app.env 或 API 密钥下载到本机。原 `.runtime/aliyun-console-access.json` 和 legacy token 保留，角色仍为 None，旧私有任务与会话没有自动共享。

演示租户为 `synthetic-p12-ecs-09531dd70185`。申请人 `applicant-demo` 与安全人员 `safety-manager-demo` 是不同 Identity、独立 token；本批真实页面操作均由同一操作人员执行，页面明确标为演示身份，不声称企业 SSO。

## 发布与数据

- 当前发布：`/opt/anlan2/releases/p12-collaboration-20261025`；原 P11 发布保留。
- 服务：`anlan2-console`，用户 `anlan2`，仍监听 `127.0.0.1:8018`，原 Nginx `/anlan/` 入口保持。
- 应用 wheel：沿用 B4 已验收制品，SHA256 `6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`。本批没有改应用源码，不把部署 helper 当成 wheel 内代码。
- 部署 helper：`/opt/anlan2/release-collaboration-20261025.py`，SHA256 `3ef15464f65296c2e53320fa3b6d04f6f7da060fc0c6e96d32cf9db8ee6b31c8`；实现提交 `1b72135`。
- 实际数据库仍为 PostgreSQL 13.23；增量 SQL017 已运行，SQL012 未启用。没有升级系统 PostgreSQL、Nginx、Python 或既有依赖。

发布前，先通过 pinned host key 的 SSH 只读检查 current、实际 systemd 进程、监听、schema、旧行摘要、角色和实时账本，并确认未完成操作、消息、核查、reserved 预算均为0。随后备份、上传并校验 wheel、验证新版依赖与配置、验证维护回滚应用，才短时切换服务。无凭据证据见 [evidence/batch-05](evidence/batch-05/manifest.json)。

备份位于 `/opt/anlan2/shared/before-p12-collaboration-20261025/`，目录0700，`database.dump`、`app.env`、`console.json` 均0600；另有发布路径与恢复策略记录。自定义格式 DB 备份经过 `pg_restore --list` 检查，SHA256 `ed82bff85ac0987619a9a606b21535929652aaf6999c84571f8112151457f22b`。没有把旧数据库或旧账本恢复覆盖当前记录。

旧业务表逐行 JSON 指纹的多重集全部保留，包含 checkpoint、私有会话、知识和预算行；迁移版本记录单独核对。实际业务增量：任务12→13、材料操作37→39、事件10→11、核查11→12、会话1→3；新协作申请1份、四项协作命令、六项协作事件与六条通知。原站点根页面 SHA256 始终为 `b5a7f25ac949b5f26ded8692c39c42f64f85cb919736f5db68bc776987515b12`。

新租户只导入仓库公开 SYNTHETIC 事实与六份公开知识文档。事实通过新增租户记录与原文件合并，未重新标记旧记录。知识使用既有 bge-small-zh-v1.5 本地神经向量组合，制品摘要 `99f12e113be380bdc60848acf108561ef3157f427b47538378967d7ef47418d7`；没有复制旧租户私聊或私人知识。固定时钟 `2026-09-22T04:00:00Z`（北京时间12:00）是合成回放，非实时现场。

## 有新协作数据时的恢复

本批回滚始终切入 `/opt/anlan2/releases/p12-maintenance-20261025`：它不加载旧业务 API 或数据库，业务路径统一503。新协作记录存在时，不能执行 P11 文档里的旧界面回滚命令，否则旧写接口不具备本期冻结约束。需要通过已授权管理通道执行：

```bash
/opt/anlan2/current/venv/bin/python /opt/anlan2/release-collaboration-20261025.py rollback
# 核对维护状态与记录后，前向恢复同一新版：
/opt/anlan2/current/venv/bin/python /opt/anlan2/release-collaboration-20261025.py forward
```

恢复过程不恢复旧 DB、不删除或退还调用次数、不把 current 切回 legacy 写应用。维护回滚是暂停业务，不提供旧界面继续写入。只维护安澜服务，未 reload Nginx 或变更无关网站。

已在新协作数据存在时实际执行 rollback→forward→再次 systemd restart。实际 PID 为3420837→3424397→3424454；维护期间五条新旧写路径均503。所有 DB 行、账本，以及双方会话、材料、业务通知、事件、currentness 和反馈在恢复前后逐字段一致。终检新旧三份 token 认证均通过，匿名401；双方访问对方私人会话、旧私有任务均404，旧身份不能读取新增共享申请。

## 实际模型用量与失败

发布前实时账本为累计79/100，对话 P11-WP01 为12/30，材料/事件 P11-WP02 为3/10。初始最小计划为7次对话、2次材料、1次事件。

安全人员确认补充要求时，分类器两次返回 `invalid_output`，均保存为 failed；当已用5次对话、剩余链路至少需要4次时，停止付费动作并请求最小增量。**用户在本批明确答复“允许本批最多9次对话尝试”**。仅本批对话尝试上限8→9；累计100、对话包30、材料/事件包10保持，无新包、额度表变更或静默重试。

最终本批9次对话（7成功、2失败）、2次材料分析、1次事件核查，共12次尝试、10成功、2失败。最终账本为累计91/100、对话21/30、材料/事件6/10；全部历史成功85、失败6。媒体制作和恢复检查没有供应商模型调用。未查询实际支付金额。

失败被服务端归为输出格式无效，有 token usage；原始供应商回复没有持久化，因此不能确定具体哪个字段不合规，也未猜测性修改应用。两次失败均未执行补充要求命令，原卡片保留。用户授权后由本人输入明确的“确认继续”并点击发送，完成原卡片；其他重要协作动作均真实点击候选与确认。失败消息与账本保留，成片也说明这一情况。不把这一次成功链路当作模型泛化或稳定性结论。

## 双身份真实主链

申请编号 `7cf090e5-8b23-5234-80c3-08a8ebdb7a8b`。

- 申请人会话：`1471099e-ce04-4537-817b-495a3c97f66e`。
- 安全人员会话：`93940ed6-a4d4-404a-9f32-9eb8a56fa0ec`。
- 四字段自然语言→创建前确认→真实材料分析revision1→选择指定安全人员、候选与确认提交→安全人员本人待办与绑定→一条未戴安全帽合成事件的事实/知识/真实模型核查与 needs_verification 人工反馈→要求具体位置补充与确认→申请人补充至revision2→说明与候选/确认重提→安全人员确认人工材料核查完成。
- 最终 application version5、completed_material_revision2，状态 `review_completed`。四项命令审计 actor 分别为申请人/安全人员/申请人/安全人员；事件核查与人工反馈 actor 为安全人员。双方不同私人 conversation 绑定同一 task。
- 事件核查三项依据为 ok，知识三条引用；初始 current，材料更新后 stale_material。原报警一直 active；反馈没有被完成材料核查清除。没有重跑成功的业务或事件模型。

## 新视频

成片：`D:\src\agent学习\安澜2.0\.runtime\anlan-dual-role-demo-20261025-film\Anlan-Dual-Role-Demo-ZH-Female.mp4`。

时长293.53秒（约4分54秒），14,602,128字节，1920×1080/30fps，H.264、48kHz双声道AAC。女声 `zh-CN-XiaoxiaoNeural`，语速-10%、音高-4Hz；[原创旁白](demo-narration.md)与中文字幕一致。SHA256：`938031adc30ab32ea91ff7ccc64b0189b122fd7b187402623d11ef343845981e`。

13章真实 ECS UI，明确申请人/安全人员切镜；创建前标为尚未生成任务，创建后显示实际同一申请编号。实际截图与视频采样匹配校准切点，缩略图平均绝对误差0.239–0.269；只放慢实际片段和延长实际结束帧，不伪造响应或时间线。完整解码、逐章实际成片音轨非静音、字幕文本/时序检查通过；关键帧人工目视核对，未将连接页或下一章当成结束冻结帧。字幕末章和片内固定标识均保留辅助核查、不批准作业边界。

素材分别保留在 ignored 的 `anlan-dual-role-demo-20261025`（首次实录及首次失败）、`…-continuation`（第二次失败）、`…-authorized`（同申请续接完成）、`…-recovery`（真实重启后只读恢复）目录；配音、SRT、ASS、剪辑时间、章节片段、QA在 `…-film`。原男声与原女声两版SHA均核对未变；音视频和访问配置没有提交 Git，仅选定无凭据PNG作为验收证据。

已知边界：合成学习环境、固定回放时钟、私密 token 演示身份；未实现 TLS/SSO/SLA、正式审批/开工授权、真实设备/P9/P10 或申请阶段证据预核查新主流程。本批提交不修改 P12 总 README/验收清单，由协调独立核对后更新。
