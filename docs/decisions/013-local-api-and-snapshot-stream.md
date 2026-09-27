# ADR013：可信本地API、持久取消和快照SSE

2026-09-27，P5-WP03。采用薄FastAPI适配已有PG工作流，默认本机合成身份/数据和替身，不新增队列、Graph或事实权威。FastAPI0.141.1/Uvicorn0.53.0由uv.lock固定；Windows启动显式Selector loop以兼容Psycopg。

宿主token→Identity和SourceBinding/FactReferences配置不从HTTP正文构造；配置重复token、含糊来源、错对象拒绝。32KiB请求上限，业务输入严格校验，错误不回显输入/DSN。仅提供材料、事件、重核和人工反馈入口，不存在批准或报警控制端点。

start可选request_id以可信身份生成稳定task ID，数据库冲突注册不覆盖旧种子；任务锁内验证mode/合同/初始字段和既有start operation。完成响应幂等，pending要求显式recover，先注册后Graph的原恢复边界不变。无request_id的原CLI仍生成新任务。

SQL008在review保存cancel_requested。取消写与结果终态选择通过同一review行锁串行；运行者轮询标记设置原取消signal，最后提交仍检查PG标记。已完成结果不受迟到取消覆盖。崩溃后的recover拿运行锁、读取原预算attempt并标interrupted或cancelled，不自动再发模型。

SSE采用PG最新快照＋内容摘要ID。订阅断开不触发业务取消，重连和进程重启后同一快照保持同一id；不是逐token流或保证所有中间事件送达的队列。原始报警始终独立，快照expired/stale不改变报警状态。

清洁启动以新venv、锁定依赖、独立wheel、离源码工作目录实际验证，同时明确复用PG和模型数据缓存。Docker/Compose及远程GitHubCI未运行，单列未验证。本机CI要求零skip，加入前后源码指纹拒绝混合版本；边界指纹不能证明整个期间不存在瞬时改写。

保留初CI395项9失败：至少4条明确为子进程无法导入build_graph，当前源码/pyc/独立进程正常，历史触发原因未证实，不能写成确定修复。复跑相关场景与冻结Gate分别记录。清洁smoke首轮先清理工作目录而服务未停，PermissionError却留passed的校验漏洞已红测复现；现先停本次服务再清理、异常置failed，Gate拒绝有error_category的报告。

工程Gate不覆盖真实模型质量。P5两次invalid_output、0/2仍为[最终质量阻塞项](../quality-items.md)，必须由后续有界诊断处理，不能以API/替身通过关闭。
