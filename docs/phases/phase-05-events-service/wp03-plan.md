# P5-WP03：本地服务、恢复与启动证据

2026-09-22，基线0dcb302。用户持续授权下直接执行；同目录，不重建业务图或账本。本包默认替身服务，零真实模型请求，WP02的0/2失败不通过追加请求掩盖。

**目标**：FastAPI暴露已有材料/事件/重核/反馈，可信身份、幂等请求、持久重核取消和SSE快照断连恢复；真实本机HTTP/重启/清洁venv与CI检查。

采用薄HTTP入口＋原服务/PG，不引入队列、Redis或第二状态权威。轮询数据库的SSE发送最新持久快照，ID为快照内容摘要；Last-Event-ID相同则不重发相同快照。此协议不是逐token流或不可丢历史事件总线，重连保证读取最新快照，可用原history/反馈审计读历史。断开SSE只结束订阅，业务操作不自动取消。

## 执行边界

- 宿主JSON配置token→Identity和来源绑定/事实引用；token/DSN仅在ignored运行目录与进程环境，HTTP正文禁止tenant/user/source授权。服务默认127.0.0.1，供本机合成演示，不是生产OAuth。请求体最多32KiB，错误不返回输入/密钥/DSN，schema额外字段拒绝。
- `POST /tasks`使用request_id，按可信身份＋request确定稳定task ID；首次注册冲突不覆盖，锁内比较初始字段和mode/contract，同请求返回同一次结果，pending提示显式recover。原不带request_id的CLI行为不变；start注册和Graph执行仍非原子，不隐式重发模型。
- GET/POST材料show/history/resume/revise/recover复用现有WorkflowService；事件receive/process/show、review/show/feedback/recover复用P5接口，感知对象引用来自宿主配置。
- SQL008增加重核cancel_requested。取消请求由owner在PG持久保存，运行者有界轮询设置原取消signal，最终结果事务再看取消标记；服务重启后recover看标记生成cancelled且不重发。已完成结果不会被后来的取消改写，不取消/解除原始报警。
- SSE GET材料/事件/重核stream，每次读仍校验归属；基于持久快照摘要，服务重启可重连。心跳与读取异常显式，断连不调用恢复或模型。
- FastAPI lifespan初始化已有迁移与依赖，Uvicorn用现有Selector事件循环（Psycopg Windows要求）；可用知识真实加载，否则显式unknown，不伪造向量。本机HTTP监听只管理本次实例。
- CI脚本运行ruff/真实PG测试/锁；GitHub配置使用Linux PostgreSQL服务与JDK21。只有实际本机运行算本机通过，未远程运行的GitHubCI与无Docker环境的Compose不得计通过。原生清洁启动从新venv安装wheel，读取同一现有PG持久任务，不停共享数据库，不杀用户chat。

## 步骤

- [x] TDD材料start幂等和PG持久取消/恢复，验证原Graph/预算/取消不退化。
- [x] TDD配置/HTTP权限/输入上限/错误脱敏/SSE ID及断连；实现interfaces/service_config、api、streams、serve与薄业务装配。
- [x] 真实子进程HTTP整链、订阅断连/Last-Event-ID/重启、并发幂等/持久取消故障验证。
- [x] 新venv/wheel原生清洁启动＋配置迁移/CI同命令实际检查，保存Docker/WSL不可用证据和未验证Compose说明。
- [x] 全量/P4/P5冻结Gate、资源/打包、账本32→32、历史/用户改动保留；更新所有文档/矩阵/学习/P6计划/handoff，阶段工程Gate满足后同目录GPT-6 Astra/high创建P6并交接。

核对的官方资料：[FastAPI生命周期](https://fastapi.tiangolo.com/advanced/events/)、[StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/)、[Uvicorn设置](https://www.uvicorn.org/settings/)、[GitHub PostgreSQL服务](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)。依赖以本次uv.lock实际解析与测试为准。
