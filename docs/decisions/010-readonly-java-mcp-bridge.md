# ADR010：少量Java API与只读MCP适配

2026-09-22，P4-WP03。Java使用JDK21内置HTTP组件，仅提供人员资质和区域状态两条回环API；转发至Python现有FactTools，不创建第二事实库或重复业务规则。Python工具继续唯一执行对象权限、资质适用性、时效和来源摘要。

两个HTTP边界分别使用启动时生成的令牌，客户端预期tenant/user/as-of通过宿主配置header传递，核心服务与自身固定身份/时点比对，不能把调用方header当授权。MCP工具Schema没有身份、时间、token或任意URL参数。接口白名单、4KiB输入、64KiB输出、Java后端2秒、HTTP客户端4秒与MCP4秒读超时均显式，父采集deadline仍在宿主；不是端到端生产SLA。

采用官方MCP Python SDK维护v1，当前锁定1.30.0，范围>=1.28,<2，实际协商协议见Gate初始化记录；不手写协议或声称实现最新2026协议全部功能。SDK单次call取消不自动发远端取消，因此在公开传输流记录实际requestId并发送CancelledNotification；408映射timeout。真实SDK内存通道验证远端handler清理，stdio上下文退出回收自建进程。已经开始的Java/Python只读I/O可到自身时限才结束，迟到结果不发布。

R1后入口interfaces/mcp_server、客户端tools/mcp、HTTP客户端tools/http_client、核心HTTP适配interfaces/fact_http，Java源码仍integrations/java。旧mcp_server保留薄命令转发。默认不安装到用户Codex全局MCP配置，不操作用户其他服务或正在运行的chat。

[工程证据](../phases/phase-04-multi-agent/evidence/wp03/verification.md)与[阶段Gate](../phases/phase-04-multi-agent/evidence/wp03/gate-final.json)。官方参考：[SDK维护文档](https://py.sdk.modelcontextprotocol.io/v1/)、[stdio协议](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[工具合同](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。这仅是合成身份、本地只读接口实践，不是生产OAuth、多用户网关或企业上线证明。
