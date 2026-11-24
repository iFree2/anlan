# M2 动态 MCP 注册与生命周期实施报告

日期：2026-11-16。范围依据 dynamic-mcp-registration-design.md 最终D批准版本。仅M2，不开放动态业务调用；M3才经本地Registry/Policy/Executor执行。

## 实施小计划

- [x] catalog：规范Schema门禁、脱敏发现、冻结目录、租户/读者/能力/厂区过滤，实际RED/GREEN。
- [x] runtime：可信profile与凭据引用隔离，官方SDK stdio/HTTP真实初始化/发现/取消/清理，生产wire无tools/call；call仅tests合成协议。
- [x] registry/CLI：显式022迁移，管理身份分离、PG版本/CAS/幂等/操作占位、跨服务scope事务锁，禁用刷新和失败恢复，实际RED/GREEN。
- [x] 集成审查与定向验收、Ruff、准确限制/回滚。

文件所有权已分配三个独立worker，均明确不得回退并发改动、不得stage/commit/切分支、零真实模型/云/部署。主窗口数据库全回归使用其他库；本包独立anlan_mcp_20261116，不drop任何库、不使用anlan_dev跑新增集。

## 实现与真实证据（2026-11-17收口）

新增实现：`tools/dynamic_mcp/catalog.py`、`registry.py`、`runtime.py`、`interfaces/mcp_registry_cli.py`、`sql/022_dynamic_mcp.sql`；新增catalog/registry/runtime/cli/integration五个测试文件及`tests/fixtures/dynamic_mcp_server.py`。小幅扩M1 contracts：原始工具名使用独立OriginalToolName（128字符、不strip、拒空白/控制字符），保留ObjectId和模型alias限制；M1原测试新增带点原名用例。

- catalog：frozen Pydantic+tuple；工具名称/规范schema字符串，不存description；Schema未知关键字/远程ref/循环/大小/深度拒绝，ref图memo验环不展开；本地八能力精确Schema比较；snapshot/report摘要自验及入口JSON重验；四重scope过滤、当前policy_version一致性、稳定目录摘要与碰撞拒绝别名。
- registry：独立AdminPrincipal/AdminPolicy，普通Identity/Bearer不授管理权；新增022显式initialize，不改旧主initializer。head/CAS、不可变revision/discovery/command、单向operation占位、expired→unknown、禁用/刷新撤权、失败receipt、同源范围排序事务锁。enable需强制宿主target/credential verifier，缺失fail closed。发现/配置输入独立快照，不信model_copy和await期间调用方修改。
- CLI：独立python -m，令牌仅宿主环境；可信配置独立重读，精确argv/目标及凭据代际，QuietParser不echo敏感非法参数，固定错误码/单行JSON、诊断概要。无diagnose/call/request-file命令。
- runtime：官方SDK1.30真实stdio与StreamableHTTP，仅initialize/list_tools/取消/关闭；不返回ClientSession，无生产tools/call。HTTP逐实际请求目标检查、禁3xx、trust_env=False、解析前512KiB累计上限并拒压缩编码防解压膨胀；最后重验授权/lease/凭据代际。取消跟踪真实wire request id，owner task保证SDK上下文同task退出并屏蔽重复调用方取消，8秒清理边界；日志只保留固定类别，stdio stderr不留存。

### RED/GREEN记录

- catalog首个有效RED：28 failed（空模块缺功能），实现28 passed；摘要/别名/目录版本4项 RED→32 passed；ref扩展深度 RED→33；旧策略三项 RED→36；带点绑定与未绑定扩展工具 RED→37 passed。
- schema DAG独立审查：8层每层5个共享ref仅1066B，修后0.000499s拒绝；保持ref图、不生成共享展开树，memo验环+最大展开深度16；八能力16份expected schema同预算生成/检查0.113429s（worker实测）。
- registry/CLI恢复点实际命令 `uv run --no-sync pytest -q tests/test_dynamic_mcp_registry.py tests/test_dynamic_mcp_cli.py` →5 failed in0.50s，缺实现；后真实PG/CLI4→7→11→14 passed阶段GREEN，覆盖跨服务竞争仅一成功、CAS、幂等、历史不可变、单次网络占位、unknown终态、refresh/disable迟到拒绝、mutable输入快照、secret参数不echo与诊断概要。
- runtime真实首轮4 passed；后新增RegistryError映射/credential轮转两个RED、JSON/SSE超限与redirect负例、主动断连/重复取消RED，逐项实现。Windows PID退出使用ctypes WaitForSingleObject真实观测，无psutil依赖。HTTP测试原未消费POST body导致TCP RST截断，修正fixture读取Content-Length后复验，不扩大超时伪造通过。
- 最终重要修复：真实PG两连接受控交错，使enable预读A后replace/discovery变B，再用B generation/digest请求；实得 `DID NOT RAISE RegistryError` RED1 failed。修为scope锁后校验预读generation/config_revision，并校验report.registration_digest绑定当前注册；GREEN1 passed in1.99s。
- runtime最后两项独立审查：gzip响应绕过raw字节上限、返回前管理授权撤销，实际RED2 failed in9.06s；拒绝非identity编码+最后authorize重检后GREEN2 passed in4.80s。
- root独立集成：真实SDK→PG验证→enable→目录→disable；真实子进程CLI（带credential_generation）→发现→缺凭据拒绝enable→恢复凭据enable→disable，2 passed in28.06s。另增真实PG禁用在途SDK发现、wire取消id与拒迟到结果，以及load_catalog旧/空策略拒绝。

### 审查过程与环境

catalog worker独立spec/quality审查registry/CLI/022，runtime由registry worker独立审查；主窗口另独立复现并反馈DAG、过期policy、HTTP前置限额、原名兼容、enable配置竞态。本窗口按上述RED/GREEN修复。被复验证伪的“SelectorLoop不能运行SDK stdio”没有当作缺陷：SDK1.30有Windows fallback，实际完整链已证明可用。

曾发生worker额度中断，保留全部RED/文件；原worker恢复继续，后再次中断时主本窗口从已有实现接手剩余修复，没有重复派工、换模型或创建窗口。

独立库`anlan_mcp_20261116`完成初版022测试后保留；022仍属本轮新增迁移，补充JSON DB约束后另建`anlan_mcp_20261116_v2`并显式基础initialize/vector，再运行最终022。未drop库、未修改已应用旧hash或旧SQL。测试读`ANLAN_MCP_TEST_DATABASE_URL`优先、显式`ANLAN_TEST_DATABASE_URL`回退，不固定dbname、不增加skip，统一回归可用单一隔离DSN。readers最终<=1000且64KiB、validation_json64KiB、lease_json4KiB。

### 限制与回滚

仍未验证真实企业服务、生产TLS/企业证书；正常HTTP仅受信IP字面量HTTPS，测试HTTP仅合成127.0.0.1固定路径。stdio官方reader没有解析前单行限额，仅受信固定程序，不能声称OS沙箱/进程内存防护。未实现M3动态模型/业务调用、别名路由或来源关系分工，不能把注册/发现当成动态业务能力完成。production Schema验证是严格规范比较，不import jsonschema、不引入依赖。

零真实模型/付费、无部署/云、无stage/commit/切分支；旧主initializer和历史SQL未修改。回滚先显式禁用本包服务并关闭进程，再撤本包新CLI/runtime/catalog/registry与测试、未应用022；已应用表与不可变审计默认保留，不降generation、不自动DROP。仅撤自有变更，不回退主窗口或其他包文件。

最终整包/旧链命令及准确结果在以下段落追加；此前开发中的混合执行曾108passed/3failed（catalog正在RED、HTTP fixture未修），不算最终验收通过。

## 最终验收

2026-11-17最终命令（宿主脚本注入凭据，Python仅在内存把本包测试DSN指定到隔离v2库；不打印DSN）：

```powershell
uv run --no-sync pytest -q tests/test_dynamic_mcp_catalog.py tests/test_dynamic_mcp_registry.py tests/test_dynamic_mcp_cli.py tests/test_dynamic_mcp_runtime.py tests/test_dynamic_mcp_integration.py tests/test_dynamic_mcp_contracts.py tests/test_tool_registry.py tests/test_tool_executor.py tests/test_tools.py tests/test_tool_loop.py tests/test_tool_model.py tests/test_knowledge_tool_loop.py tests/test_business_bridge.py
uv run --no-sync ruff check src tests scripts evals
git diff --check -- <本包所有源码、测试与报告路径>
```

实际：**198 passed in118.88s，exit0，无skipped/warnings**；全库Ruff **All checks passed!**；本包diff检查无输出exit0。完整仓库非live由主窗口统一复验，本窗口不代签其门禁。

M2已形成可审查闭环，独立审查已复现important全部有修复/回归；M3依用户排序要求另写详细设计，D通过前不实施。上述四项实施小计划均已完成（catalog/runtime/registry-CLI/集成验收）。
