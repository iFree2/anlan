# P2-WP05：本地追踪与阶段Gate

基于e941074，按持续授权自动实施。目标是在一种实际运行的平台中按task/run定位模型、工具和检索来源，并完成P2冻结工程验收。不开新模型实验，累计从12/100保持核对。

## 平台选择

已优先评估Langfuse：官方本地部署要求Docker/Compose，本机无Docker/WSL/管理员且没有云端连接凭据。选择Jaeger2.21.0官方Windows单二进制，使用标准OTLP/HTTP；不把它称作Langfuse，也不宣称具有其LLM专属实验/定价功能。JSONL继续是本地证据，Jaeger内存仅作可查询展示。

- [x] `scripts/install_jaeger.py`固定官方URL/大小/SHA256，只解压项目.runtime中允许文件，冲突拒绝；`scripts/dev-jaeger.ps1`提供Start/Stop/Env/Status，隐藏窗口，停止前严格核对进程路径/启动时间。仅监听回环地址，端口冲突不停止未知进程。
- [x] `examples/observability/jaeger.yaml`最小内存配置，HTTP查询16686与OTLP4318，其他开启端口也必须回环，禁外部AI/遥测连接。保留官方版本、文件校验及监听证据。

## 应用接入

- [x] `src/anlan/telemetry.py`将既有结束事件映射为标准OTLP span，run为trace，task/correlation为关联属性；模型/工具为子span，真实测得的elapsed_ms转换为时间区间。旧无耗时事件标记not_recorded，不补造测量。
- [x] JsonlTrace可选从可信宿主ANLAN_OTLP_ENDPOINT启用，限制本地回环HTTP且无用户信息/重定向；默认不开网络。导出失败不吞材料/工具结果，明确trace_export_failed，JSONL仍保留；本地文件失败仍trace_write_failed。
- [x] 仅导出关联ID、步骤、工具/结果/停止类别、来源版本/摘要/chunk与已知用量；白名单禁止原始材料、问题、quote、事实正文、密钥、响应或隐藏推理。
- [x] 增补模型/工具/循环实际耗时和mode。HTTP替身测试ID关联、属性白名单、失败与超时、无隐式重试；既有流程不退化。

## 实际平台与P2出口

- [x] 用明确scripted模型+真实文件/PG/本地编码形成三工具live spans，查询Jaeger API核对父子关联与知识来源；注入一次知识错误，按run定位错误工具。无新增DeepSeek请求。
- [x] 若展示旧真实记录，仅标为archived_import的只读轨迹导入，保持原始时间/缺口，不冒称新请求或Agent回放；不为平台演示重跑真实模型。
- [x] 新建P2冻结工程检查口径与manifest：工具/身份/错误/知识版本时效/引用/有界停止/观测失败/预算证据；结合全量PG测试、运行演示、既有真实小样本及Badcase，不将一套替身当全部Gate。
- [x] 独立规格/质量审查，更新README、架构、status、矩阵、学习、阶段handoff；保持个人掌握待验。Gate通过后同目录新建GPT-6 Astra/high的P3任务，携带长期授权、余额及用户原有未提交改动；不再停在常规确认。

官方来源：[Jaeger部署](https://www.jaegertracing.io/docs/2.21/deployment/)、[配置](https://www.jaegertracing.io/docs/2.21/deployment/configuration/)、[Langfuse本地部署](https://langfuse.com/self-hosting/deployment/docker-compose)。Jaeger发布资产`jaeger-2.21.0-windows-amd64.zip`64683817 bytes，SHA256 `197c4b42aba6983b3d9cbca3577a0e14191bcb9431fde1b6661471b6fece39fc`。
