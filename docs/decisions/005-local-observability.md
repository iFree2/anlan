# ADR005：JSONL与本地Jaeger观测

日期：2026-09-21。P2-WP05采用。已优先评估Langfuse官方本地Docker/Compose方案；本机无Docker/WSL/管理员，亦无已连接云项目，因此选择官方Windows单二进制Jaeger2.21.0。没有安装两个平台，不冒称Jaeger具有Langfuse的LLM评测/定价功能。

使用标准OTLP/HTTP JSON；run映射为trace，模型/工具为子span，结束事件为root。task/correlation保留为属性，source仅导出版本、摘要、记录/chunk等元数据；不导出材料、问题、quote、事实正文、凭据、原始响应或隐藏推理。实际elapsed转换为时间区间，旧记录无耗时则duration_recorded=false，不把显示的瞬时事件当测量值。

JSONL先落盘；可选可信环境ANLAN_OTLP_ENDPOINT仅接受无凭据的本地HTTP回环路径，默认关闭。请求/响应有大小界限、I/O超时且无重试或重定向。普通exporter故障在追踪边界转trace_export_failed，材料和工具结果继续；BaseException保留退出/取消语义。此策略仅适用于当前本地只读辅助演示，不授权高影响业务写操作绕过审计。

旧JSONL的只读导入使用独立trace ID与archived_import标签，保持原始时间/缺口，不覆盖live trace，也不执行工具或模型。Jaeger内存缓存不是恢复或预算权威；业务/记忆继续由PG承担，模型预占账本独立。模型step不是付费请求数，实际请求以attempt_id和共享账本核对。

安装器固定官方包大小/SHA，文件冲突拒绝；PowerShell7脚本仅管理项目实例，PID、路径、启动时间共同确认，隐藏窗口，监听仅回环。UI本地可用，不宣称生产多租户观测权限、HA或长期留存。

来源：[Jaeger部署](https://www.jaegertracing.io/docs/2.21/deployment/)、[Jaeger配置](https://www.jaegertracing.io/docs/2.21/deployment/configuration/)、[OTLP JSON规范](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding)、[Langfuse Compose](https://langfuse.com/self-hosting/deployment/docker-compose)。
