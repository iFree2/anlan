# 本地服务与验证边界

服务默认仅绑定127.0.0.1，身份来自宿主配置的Bearer token；材料、事件正文不能提交租户/用户或重核事实引用。全部数据为SYNTHETIC，材料分析offline、感知模型scripted_double。本服务没有真实模型启用选项；P5真实模型质量仍未通过[Q-P5-001](../../quality-items.md)。

## 原生启动

```powershell
scripts/dev-postgres.ps1 -Action Env
.venv/Scripts/python.exe scripts/prepare_service_demo.py --output .runtime/service-demo-new.json
.venv/Scripts/python.exe -m anlan.interfaces.serve --config .runtime/service-demo-new.json --port 8000
```

准备命令创建两个合成材料任务、摄取P5示例知识、生成来源绑定和本地随机token；不会打印token。配置中固定2026-09-22T04:00Z回放时钟，并使用绝对事实/模型缓存路径。每次用新配置路径，避免覆盖运行实例凭据。查看配置令牌仅供本地调用，不提交该文件。

```powershell
$demoConfig = Get-Content .runtime/service-demo-new.json -Raw | ConvertFrom-Json
$demoHeaders = @{ Authorization = "Bearer $($demoConfig.tokens[0].token)" }
Invoke-RestMethod http://127.0.0.1:8000/readyz -Headers $demoHeaders
```

`POST /tasks`要求request_id和fields，重复返回同一次创建结果；当前状态用GET读取。`POST /tasks/{id}/resume`只补充waiting_input；`revise`只重核awaiting_review；`recover`显式恢复未完成材料操作。提交合同包含request_id、expected_revision、fields。start回应丢失时可用`GET /tasks/by-request/{request_id}`定位同一任务。

`POST /sources/{source_id}/events`接收两类原事件；`POST /events/{receipt}/process`只关联；`POST /events/{receipt}/reviews`只接request_id，事实引用来自宿主配置。`GET /reviews/{id}`返回原结果及当前性；feedback只允许confirmed_event/disputed_event/needs_verification与期望revision。`cancel`持久保存取消意图；`recover`在旧运行锁释放后标interrupted或cancelled，不重发模型。上述确认指的是合成事件反馈，不能批准作业或解除告警。

## SSE语义

`GET /tasks/{id}/stream`、`/events/{id}/stream`、`/reviews/{id}/stream`发送event=snapshot，id是快照内容摘要。Last-Event-ID与当前摘要相同时不重发相同快照，之后变化会生成新id；5秒心跳。断连只停止订阅，不取消业务或重放模型。服务重启后从PG读取持久快照，可使用旧id重连。

这是“恢复到最新快照”，不是逐token流，也不是保证每个历史中间状态都送达的事件队列。原材料history和反馈审计保留历史。每次读取都受归属校验；请求体最多32KiB，错误返回固定分类而不回显正文/连接配置。

## 实际验证与未验证部分

干净venv使用uv.lock导出的非开发依赖与独立wheel，从临时工作目录通过`python -I`启动，确认包路径位于该venv的site-packages；事实/编码器缓存和PG为明确复用的外部数据依赖，不声称新建了整个操作系统或数据库。`scripts/smoke_service.py`验证两类事件、模拟反馈、SSE断连重连和进程重启，退出只终止本次服务。

本地CI：`scripts/dev-postgres.ps1 -Action Env`后运行`.venv/Scripts/python.exe scripts/ci.py --output .runtime/ci-new.json`。它检查锁文件、ruff、完整pytest和零skip，并比较运行前后源码指纹；执行期间不要编辑源码。使用新输出路径保留旧失败。

本机无Docker/Compose且WSL组件不可用。Dockerfile/compose.yaml只是未执行模板，不能算部署通过；Compose数据库使用55433以避开既有55432。将来验证需先准备目标数据库中的任务/知识与容器内路径配置，不能把现有Windows配置和另一个数据库的task ID直接照搬。新数据库不能用来重置或绕过真实模型预算。

GitHub工作流已配置Linux、PG17/pgvector、JDK21及相同CI脚本；本任务没有推送或远程运行，因此远程CI未验证。官方依据：[FastAPI流式响应](https://fastapi.tiangolo.com/advanced/custom-response/)、[PostgreSQL服务容器](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)、[uv Actions](https://docs.astral.sh/uv/guides/integration/github/)、[pgvector镜像](https://github.com/pgvector/pgvector)。
