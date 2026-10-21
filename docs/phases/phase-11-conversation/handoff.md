# P11 对话入口交接

## 本地启动

```powershell
Set-Location 'D:\src\agent学习\安澜2.0'
scripts/dev-postgres.ps1 -Action Start
scripts/dev-postgres.ps1 -Action Env
.venv/Scripts/python.exe scripts/prepare_console_demo.py --output .runtime/conversation-demo.json
.venv/Scripts/python.exe -m anlan.interfaces.serve --config .runtime/conversation-demo.json --port 8000
```

打开 http://127.0.0.1:8000/console，选择新生成的配置。配置文件含本地 bearer token，只保存在已忽略的 `.runtime`，不上传、不打印正文。重复生成必须换新输出路径。

本次协调会话另启动了本地预览：http://127.0.0.1:8130/console，选择 `.runtime/conversation-preview-20261021.json` 连接。该进程使用 scripted_double，仅供本机体验；进程退出后可按上述命令重新启动。

## 读取顺序

1. `conversation/contracts.py` 与 `policy.py`：模型候选和宿主决策分离。
2. `conversation/service.py`：一条消息的预留、分类、路由、业务调用和完成回执。
3. `infrastructure/conversations.py` 与 SQL013：归属、revision、幂等、锁与恢复。
4. `llm/conversation.py`：scripted_double 只是控制流替身；DeepSeek 边界严格传播 `target_task_id`。
5. `interfaces/conversation_runtime.py`：唯一允许写材料工作流的对话适配器。
6. `interfaces/conversation_routes.py` 与 console assets：认证 HTTP、最新快照 SSE、对话和任务侧栏。

## 安全与恢复边界

- 候选意图不是业务任务。`START_HOT_WORK` 只能来自已保存候选的明确确认。
- 活动任务上的另一项申请先进入新建/切换选择，旧任务保持；只有“新建另一项任务”等显式选择才进入新申请确认。
- “不要把位置改成二号罐区”和“我不想新建”有回归，不写材料、不意外推进。
- 同 request_id 同载荷回放原结果；改载荷、旧 revision、越权与并发处理中写入拒绝。失败分类实例持久化且重放语义不伪装成成功。
- 休眠/取消引导只改会话绑定，不改审批、原始报警或人工决定。

## 当前证据与未完成项

定向真实 PG 98 项；协调最终全套 576 passed、0 skipped，Ruff 通过。最终 wheel 离源码启动/重启恢复及本地预览 smoke 通过，详见 [Gate](evidence/gate-report.md)。批次4浏览器已实际交互验证主链、拒绝、暂停/恢复、切换、事件/核查和 390x844；截图文件保存工具在长 SSE 页面阻塞，未重复尝试。

P11-WP01 真实请求为 0，live 分类/闲聊质量未验；本地 46/100 只是冻结学习账本，不是当前云端余额。原云端 DeepSeek 版未发布本次改造；本次未 SSH、未部署。P9/P10 仍是独立未完成计划。
