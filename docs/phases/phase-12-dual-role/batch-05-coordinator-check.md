# P12 B5 协调独立验收

日期：2026-10-25（Asia/Shanghai）。实施提交 `1b72135`、交接 `9b538d3`；基线 `45f9300`。协调未改业务应用或发布helper，没有新增真实模型调用。

## 独立执行

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_deployment.py tests/test_conversation_release.py --junitxml=.runtime/p12-b5-coordinator-tests.xml
.venv/Scripts/python.exe -m ruff check src tests evals scripts deploy
git diff --check
.runtime/media-venv/Scripts/python.exe .runtime/p12-b5-verify-media.py
```

部署测试 **14 passed，0 failures/errors/skipped，0.72s**，现有Starlette/AnyIO弃用警告1条；Ruff与diff检查通过。未执行live pytest、未重复模型联调，不把B4的905项算成本批新增测试。独立JUnit保存于[evidence/batch-05-coordinator/deployment-tests.xml](evidence/batch-05-coordinator/deployment-tests.xml)。

逐一核对B5 manifest中42份证据、ignored源清单35份媒体的SHA256均一致。实际helper SHA为 `3ef15464f65296c2e53320fa3b6d04f6f7da060fc0c6e96d32cf9db8ee6b31c8`；应用wheel仍为B4验收制品 `6024af9350d518e29eb0610bbfeedbbee2567669d13a70f62641fca2c68b1bb6`。本批没有应用源码变化。

## 云端只读复查

协调先读取并检查ignored `.runtime/p12-b5-final-remote.py`：只进行GET、只读PG、制品/进程/哈希检查，不切换服务、不写账本或调用模型。随后经既有私密SSH桥接、RejectPolicy固定主机指纹实际重跑，输出保存于[cloud.json](evidence/batch-05-coordinator/cloud.json)。没有打印或提交认证配置、DSN、供应商密钥。另检查公网控制台200、匿名API401。

结果：current是 `/opt/anlan2/releases/p12-collaboration-20261025`，服务active、用户anlan2、PID3424454；PG13.23含SQL017且不含012。125份安装文件与固定wheel逐字节相同，真实cwd/PYTHONPATH正确。发布前旧行逐行指纹多重集仍保留；原根站点SHA为 `b5a7f25ac949b5f26ded8692c39c42f64f85cb919736f5db68bc776987515b12`，未变。

两新增角色和原legacy角色分别正确认证；同申请 `7cf090e5-8b23-5234-80c3-08a8ebdb7a8b` 在双方均为review_completed/version5/completed_material_revision2。两私人conversation不同，互读404；新增角色读旧私有任务404、legacy读新共享申请404。所有pending/reserved为0。

终检预算91/100、对话21/30、材料/事件6/10，与交接一致。只读审查attempt-audit确认本批12条唯一尝试、9对话+2材料+1事件、10成功/2失败。用户已在B5原会话明确授权本批对话8→9；原100/30/10与旧包保持。两次invalid_output未推进业务命令、未退还次数；原始供应商回复未保存，具体字段根因未知，不宣称模型可靠性已修复。

维护回滚不重复实切，以B5实际恢复证据及代码审查复核：五条新旧写路径均503，rollback→forward→restart的真实PID变化、DB/双方业务快照一致。helper仅允许NEW/MAINTENANCE，维护应用不加载旧业务/DB，无数据库恢复或账本抹除路径。已给P11历史部署文档加醒目禁用旧界面回滚警告。

## 视频复验

独立重跑成片QA：完整H.264/AAC解码退出0，1920×1080/30fps、48kHz双声道；13章从最终成片解码的音轨RMS均大于100，逐章字幕与旁白一致，时序合法，旧两版媒体哈希未变。[media.json](evidence/batch-05-coordinator/media.json)保留结果。

实际成片293.53秒、14,602,128字节，SHA `938031adc30ab32ea91ff7ccc64b0189b122fd7b187402623d11ef343845981e`。独立目视补充要求、事件三依据ok、人工完成关键帧：同一申请、不同角色、明确补充问题、人工说明、旧事件stale/原报警active、合成固定时钟和不批准作业边界可读。此为协调重跑媒体QA与证据复核，不冒称协调再次操作整条付费浏览器链。

成片及两私密角色配置绝对路径见[部署与交付](deployment.md)；原始失败素材、各轮实录和制作源均保留。慢速柔和合成女声为XiaoxiaoNeural/-10%/-4Hz，无真人声音仿冒。

## 审查与结论

独立只读审查者实际检查 `45f9300..9b538d3` 发布实现、测试、部署文档与证据，**未发现Critical、Important或Minor**；没有运行测试/SSH/模型调用，与协调独立执行分开记录。

G5六项全部满足，B5验收通过；B1—B5及本期G1—G5完成。更新总README/验收/当前状态，最终交付后删除p12持续跟进。保留用户roadmap、status中P10原段落、P10目录、live测试与.superpowers未提交路径；不git add -A。终点仍是合成学习环境的人工材料核查完成，不提供正式审批、开工授权、真实设备、TLS/SSO/SLA，不自动开始P9/P10。
