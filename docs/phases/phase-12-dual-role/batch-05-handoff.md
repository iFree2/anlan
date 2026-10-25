# P12 B5 交接：ECS、有限真实联调与双角色女声视频

日期：2026-10-25（Asia/Shanghai）。起点为 B4 协调放行 `3dde269`。部署 helper 与测试实现提交 **`1b72135`**；本交接、部署说明、旁白与无凭据证据以随后文档提交交付，可用 `git log -1 -- docs/phases/phase-12-dual-role/batch-05-handoff.md` 查询。

本批交付已完成，交协调独立复核；没有擅自修改总 README 或 acceptance.md，也不把本会话自检称为独立验收。沿现有 local 检出串行实施，未创建 worktree、后续会话、子代理或向其他会话发消息。

## 实现与 RED / GREEN

新增 `deploy/aliyun/release_collaboration.py`、`tests/test_collaboration_deployment.py`。helper 提供 inspect/prepare/activate/rollback/forward：实时账本与未完成操作检查、私密备份、固定 wheel 校验与依赖验证、legacy 身份保持、新租户双角色及合成事实配置、原子 current 切换和认证就绪检查；回滚始终进入不加载旧业务处理器或数据库的维护应用，前向恢复回同一新版。没有改应用源码或 SQL012，没有预算重置、扩包或系统组件升级。

先增加具名失败测试，实际 RED 为 **11 failed / 0 errors / 0 skipped，1.73s**：缺少预算计划、未完成操作门控、独立身份配置、事实合并、维护写入封锁、回滚、wheel 路径检查和备份/数据变化门控。最小实现后连同 P11 相邻发布测试得到14 passed。最终验证：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_deployment.py tests/test_conversation_release.py --junitxml=.runtime/p12-b5-deployment-final.xml
.venv/Scripts/python.exe -m ruff check src tests evals scripts deploy
git diff --check
```

最终 **14 passed / 0 failures/errors/skipped，1.43s**；现有 Starlette/AnyIO BlockingPortal 产生1条弃用警告，未隐去。Ruff `All checks passed!`，diff 检查通过。首次 Ruff 的7处行长问题修正后通过。B5部署测试不使用PG替身冒充数据库验证：纯函数和维护应用测试本身不需要PG；云端迁移、旧行与真实恢复另在 PostgreSQL13.23 实际检查。未重跑或挪用 B4 905项当作本批测试，未执行用户未提交的 live pytest。

本批没有应用修复，故沿用已由 B4 全仓/Gate 验证的 wheel：`.runtime/p12-b4-dist/anlan-0.1.0-py3-none-any.whl`，SHA256 **`6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`**。云端125个实际安装文件逐字节匹配该 wheel；实际服务 cwd 为新版发布，PYTHONPATH仍为 `/opt/anlan2/current/app`。helper 不在应用 wheel 内，单独 SHA256 **`3ef15464f65296c2e53320fa3b6d04f6f7da060fc0c6e96d32cf9db8ee6b31c8`**。

## 云端发布、数据和回滚

入口：[http://47.93.218.52/anlan/console](http://47.93.218.52/anlan/console)。当前发布 `/opt/anlan2/releases/p12-collaboration-20261025`；服务 `anlan2-console`、nonroot `anlan2`、127.0.0.1:8018、原 Nginx `/anlan/` 保持。只维护本应用，未 reload Nginx 或操作无关网站。

SSH 管理认证仅在进程内从 ignored 私密文件读取，主机指纹以 known-hosts 的 RejectPolicy 核验；未打印密码、完整 DSN、API key、token 或私密配置正文。仅将新增两份客户端配置下载到 `.runtime/p12-b5-access/`，没有下载 app.env 或服务器供应商密钥。

备份 `/opt/anlan2/shared/before-p12-collaboration-20261025/`：目录0700、DB/env/config0600，记录原发布路径、旧行指纹及恢复策略。DB自定义备份通过列表检查，SHA `ed82bff85ac0987619a9a606b21535929652aaf6999c84571f8112151457f22b`。准备和切换前均确认没有 pending 操作/消息/核查或 reserved 预算；备份、上传SHA和兼容探针全部通过后才停旧服务切换。新增SQL017，未启用SQL012；原PG13.23与依赖保持。

旧表所有业务行及账本行的逐行指纹多重集保留，不只是比较总数。任务12→13、材料操作37→39、事件10→11、核查11→12、会话1→3，新增一份协作申请、四项协作命令、六项事件和六条通知。原根站点 SHA `b5a7f25ac949b5f26ded8692c39c42f64f85cb919736f5db68bc776987515b12` 未变。

旧 P11 发布保留；新协作数据存在时**不得调用旧 P11 界面回滚脚本**。本批的 `/opt/anlan2/release-collaboration-20261025.py rollback` 切入 `/opt/anlan2/releases/p12-maintenance-20261025`，所有业务路径503；`forward` 切回同一新版。没有恢复数据库、删除或退还账本。先在云端以实际 nonroot 独立进程验证维护应用，再在本批协作数据存在时实切 rollback→forward→systemd restart。五条新旧写入路径503；所有DB行与双方业务快照跨恢复完全一致。实际服务PID **3420837→3424397→3424454**。详见 [recovery.json](evidence/batch-05/recovery.json)、[最终运行制品与权限](evidence/batch-05/final-cloud.json)。

## 私密角色配置与真实链路

本机配置：`D:\src\agent学习\安澜2.0\.runtime\p12-b5-access\applicant.json`、同目录 `safety-manager.json`。服务器原件在 `/opt/anlan2/shared/p12-collaboration-20261025/`；原 legacy token 及私有历史保留，仍无协作角色。新tenant `synthetic-p12-ecs-09531dd70185`，不同 Identity/独立 token。两独立 browser contexts 使用两份本人配置，页面明确是演示身份，由同一操作人员分别操作，没有代办或借申请人 Identity 执行安全人员动作。

- 同一 task：**`7cf090e5-8b23-5234-80c3-08a8ebdb7a8b`**。
- 申请人 conversation：`1471099e-ce04-4537-817b-495a3c97f66e`。
- 安全人员 conversation：`93940ed6-a4d4-404a-9f32-9eb8a56fa0ec`。
- 实录完成：四字段自然语言→创建确认/真实材料分析→UI候选/确认提交→安全人员本人待办/绑定→事件核查/反馈→具体位置补充要求及确认→申请人自然语言更新revision2→UI候选/确认重提→安全人员UI候选/确认材料核查完成。最终 application version5、completed_material_revision2，`review_completed`，不是 approved。
- 新事实仅对新tenant加入公开SYNTHETIC夹具，旧租户事实保持；合法导入六份公开SYNTHETIC知识，使用既有 bge 神经向量组合，无旧私聊/私人知识复制。固定回放时钟 `2026-09-22T04:00:00Z` 明确标注，非实时现场。
- 只做一条未戴安全帽合成事件；资格、区域、知识三项outcome均ok，知识三条引用，模型综合为deepseek_live。真实actor为安全人员；needs_verification反馈保存，原报警active。材料更新后原核查stale_material，没有为重拍重跑事件模型。
- 进程恢复后两端申请、通知/业务时间线、事件、currentness和反馈逐字段相同。私聊互读404、新身份读旧私有任务404、legacy读新共享申请404、匿名401。浏览器local/session storage为空。

## 预算变化与必要新授权

实时发布前：累计79/100，对话12/30，材料/事件3/10。原本最小计划7对话+2材料+1事件。安全人员确认要求补充时，两次分类输出校验失败，实际failed并计入账本，命令未执行；失败后的实时快照为累计86、对话17、材料/事件5，未完成操作均0。

此时本批已经5/8次对话，完成余链至少需要4次，故停止付费并询问最小增量。用户明确答复 **“允许本批最多9次对话尝试”**；只调整本批上限8→9，累计100、P11-WP01=30、P11-WP02=10不变，不开新包。用户授权后输入整句“确认继续”并点击发送，确认原卡片；随后沿原task完成余链，没有重跑已成功步骤。

最终本批：**9次对话（7成功/2失败）+2次材料+1次事件=12次尝试，10成功/2失败**。最终累计 **91/100**、对话 **21/30**、材料/事件 **6/10**，全部历史成功85/失败6。最终没有reserved/pending。媒体和恢复工作新增业务模型调用0。没有查询实际账单金额。

失败原因仅能确定为供应商输出 `invalid_output`；usage已留存，但原始供应商回复未持久化，不能声称已定位某个具体字段或已修复模型可靠性。没有猜测性改应用，没有静默重试、账本退款或删失败记录。两次失败原始报告/画面/视频均保留，成片旁白也说明失败未推进业务。部署初期另有只读SQL列名误用、Windows桥接编码/本地上传路径失败，均在付费前修正，没有当成模型失败或抹掉业务调用。

## 新视频与QA

最终成片：**`D:\src\agent学习\安澜2.0\.runtime\anlan-dual-role-demo-20261025-film\Anlan-Dual-Role-Demo-ZH-Female.mp4`**。

**293.53秒，14,602,128字节，1920×1080/30fps，H.264/AAC，48kHz双声道。** 女声 `zh-CN-XiaoxiaoNeural`、rate=-10%、pitch=-4Hz；原创口语旁白见 [demo-narration.md](demo-narration.md)。最终SHA256 **`938031adc30ab32ea91ff7ccc64b0189b122fd7b187402623d11ef343845981e`**。

13章均取实际ECS画面。不同角色明确切镜、创建后显示同一真实申请编号，创建前另标尚未生成任务；全片保留合成数据/辅助核查/不批准作业和固定回放时间。字幕在长句处按标点换行，未将一个“失败”拆行。截图与视频采样匹配校准每个实际媒体切点（缩略图平均绝对误差0.239–0.269）；实际片段放慢，结束帧只在本章已核对结果内延长，没有连接页或下一章误冻帧，没有伪造响应/时间线。

最终完整解码 `-xerror` 返回0；13章**从最终成片重新解码**的音轨均非静音，字幕文案与配音逐章匹配且时序在音轨内。关键帧人工目视核对了创建前、补充要求、事件三项ok/current、stale、双方完成、重启后反馈；旧男声及女声两版SHA均保持。见 [media-verification.json](evidence/batch-05/media-verification.json) 和 film-*.png。

ignored原始素材目录：`.runtime/anlan-dual-role-demo-20261025/`、`…-continuation/`、`…-authorized/`、`…-recovery/`；配音/字幕/ASS/章节片段/成片/解码日志/实际切点在 `…-film/`。录制脚本 `.runtime/p12-b5-record.py`、`p12-b5-recovery-record.py`；制作脚本 `p12-b5-voice.py`、`p12-b5-align.py`、`p12-b5-render.py`、`p12-b5-verify-media.py`。8份原始视频、13份MP3、13份SRT及成片共35份媒体SHA另列于 [ignored-media-sources.json](evidence/batch-05/ignored-media-sources.json)，没有提交私密配置或音视频；仅选定无凭据PNG作为验收证据。

## 范围保持与交协调

详细使用/恢复说明：[deployment.md](deployment.md)。本批证据清单：[manifest.json](evidence/batch-05/manifest.json)，包含红绿JUnit、live实际预算/失败、云端备份/回滚/制品/权限、双浏览器恢复、知识、成片QA与关键帧；扫描私密token/SSH密码未发现泄漏。首次暂存检查发现Windows生成的CRLF在证据目录-text规则下被判行尾空白，已将提交证据规范为LF并去除pytest展示的尾随空白；JSON数据、测试数量/失败信息未改。目录gitattributes固定bytes，原始JSON/JUnit仍在ignored目录，manifest重新按规范后的bytes计算。

本批所有浏览器录制context关闭；云端只保留正式新版服务；独立维护探针PID3420557已退出且18018关闭。没有宽泛清理、全杀进程或递归删除旧目录，PG及全部历史媒体保留。原用户dirty路径 `docs/roadmap.md`（3行）、`docs/status.md`（2行）、P10目录、`tests/test_tool_loop_live.py`、`.superpowers/` 保留，不reset/checkout，不git add -A。

G5所需发布/预算/恢复/双角色视频证据已交付；总清单由协调独立核对后更新。限制仍为合成学习环境、演示token、固定回放时钟；没有正式审批、开工授权、TLS/SSO/SLA、真实设备/P9/P10或申请阶段证据预核查新主流程。本会话不启动后续工作。
