# P4-WP03在途实现基线（分包重构前）

2026-09-22。Java两条HTTP只读门面→Python现有FactTools，官方MCP1.30.0维护v1 SDK stdio适配；pyproject限制>=1.28,<2，uv.lock固定全部依赖。本机JDK21.0.6，未建立第二事实权威，无模型凭据/新请求。

- [cancel-corrected.xml](cancel-corrected.xml)：17项真实Java/HTTP/MCP及SDK内存通道测试通过，含授权、身份错配、时点、非法工具/参数、过大请求、后端不可用/超时/过大响应、取消通知与SDK408映射。
- [bridge-corrected.json](bridge-corrected.json)：3个既有真实PG任务、BGE知识/Memory，同材料/时点/对象直接Python与MCP→Java→Python证据一致；接P4两角色替身完成，模型预算30→30。自建Java进程已停止。使用python -O运行，不依赖assert作为脚本Gate。
- 全量重构前基线291项通过（34真实PG、0跳过）：[pytest-baseline.xml](pytest-baseline.xml)；阶段完整Gate尚未执行，因用户新增优先分包重构，安全收束本包后先重构再恢复Gate。不把当前状态写作P4阶段通过。

失败保留：初次uv add安装因用户已有`uv run anlan chat`占用anlan.exe失败，未终止用户进程；改uv add --no-sync＋uv pip install安装依赖，验证用.venv/Scripts/python.exe。普通uv run可能仍尝试重装入口；当前uv lock --check可独立通过。

12项早期测试没有发现host身份与token绑定backend身份不一致会误读数据；scope-red复现后加入可信配置header传递并由Python核心固定身份/as-of比对，不把header当身份授权或模型参数。缺少/错误配置拒绝。

SDK1.30的单次call取消不自动发送远端取消，SDK读超时抛McpError(408)。真实官方SDK内存通道2红后，在公开write stream边界捕获实际requestId并发送CancelledNotification，不依赖私有计数器。首版包装缺少异步上下文方法导致5失败（cancel-green.xml命名是尝试结果、不是成功声明），bridge-initial.json为0例失败；补上下文转发后17项和3例整链通过。原失败工件不重写。

限制：MCP取消通知能停止合作式远端handler；Java/Python底层已经开始的只读I/O仍可能到自己的截止时间才结束，无业务写入、迟到不发布。服务只绑定回环、启动配置一个合成身份/时点、双令牌边界；不是生产OAuth、多用户网关或端到端SLA。子进程结束只管理本次自建进程，不操作用户已运行chat。
