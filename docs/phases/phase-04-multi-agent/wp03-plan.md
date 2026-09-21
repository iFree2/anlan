# P4-WP03：少量Java API、MCP适配与阶段Gate

2026-09-21，基线f4c4a47。WP02最终274测试，真实9请求后累计30/100。依持续授权自动实现，本包不读模型凭据/不请求模型。

## 设计和边界

选JDK21内置HttpServer/HttpClient提供人员资质、区域状态两条HTTP接口，Python现有FactTools仍为唯一业务规则/合成文件来源。Java做路径白名单、令牌入口、大小/超时限制和错误转译，再转发私有回环Python适配器；不复制资质/有效期/授权业务规则，不写Graph/数据库。比再建Java事实库更容易验证一致；比直接跳过Java满足本阶段实际跨语言调用学习范围。

MCP采用官方Python SDK维护v1并显式<2锁定，协商已有2025协议，不手写协议或声称最新2026功能；SDK负责stdio初始化、tools/list、tools/call和取消。仅两只读工具，参数不含tenant/user/as-of/token，启动可信环境映射一个合成身份和固定时点。HTTP两个边界令牌不同，只监听127.0.0.1，不安装到全局Codex配置，不声称生产OAuth/多租户认证。

`McpFactTools`提供原FactTools接口供P4采集器使用；先核对调用身份与会话身份，再发MCP。返回必须验证ToolResult/对象/时点并保留source，传输失败显式未知。受控fan-in和父预算继续生效，MCP不扩工具权限。实际跨进程链为P4宿主→MCP子进程→Java API→Python现有工具，Knowledge/Memory仍本地PG。

## 实施/验证

- [ ] 锁定SDK依赖；记录官方协议/SDK来源与实际版本。
- [ ] 红测`tests/test_business_bridge.py`：原规则实际HTTP、缺token/身份参数/越权对象、非白名单、过大输入、Java后端不可用/超时、返回合同。
- [ ] `business_bridge.py`私有Python只读适配、`integrations/java/AnlanFactApi.java`两路径门面、`mcp_server.py`官方SDK stdio与`mcp_tools.py`宿主客户端适配。无Graph写连接共享。
- [ ] `scripts/smoke_business_bridge.py`管理临时端口与子进程（finally终止自建进程），用真实SDK client握手/list/call，并经McpFactTools跑真实PG/P4双角色替身完整链路；同任务直接Python/跨语言证据比较。
- [ ] 红绿故障测试、全量与ruff/uv lock；P4冻结Gate验证WP01/02同任务和Java/MCP路径、失败保留、共享生产账本零增量，并在python -O运行。原P3/P2冻结回归不可跳过，Jaeger Env明确加载。
- [ ] 更新状态/矩阵/学习/ADR/阶段handoff与P5 plan/acceptance，保留成本/延迟/语义坏例；阶段工程Gate通过才创建同目录GPT-6 Astra/high P5任务。

官方参考（2026-09-21核对）：[SDK维护线](https://py.sdk.modelcontextprotocol.io/v1/)、[低层服务](https://py.sdk.modelcontextprotocol.io/v1/low-level-server/)、[stdio传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[工具合同](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。维护线是明确范围选择，不把2025协议写作最新标准。
