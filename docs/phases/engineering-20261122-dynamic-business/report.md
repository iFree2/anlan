# P10 人员业务增量包报告

日期：设计与门禁2026-11-22，实施/验证2026-11-23。任务B仅人员三能力；作业票未实施。状态：人员55项全部通过且独立审查关闭；完整回归334通过/4项冻结旧链失败，待总窗口复验，尚未可发布。

总窗口已明确批准 design.md：可信宿主目录的承包商ID、人员ID、关系、厂区及类别分别冻结；重名要求显式ID；资质/培训/准入不可互替；复用同一本地执行边界，独立工作流，不改冻结核心。

## 实现与边界

新增 personnel.py 提供 Contractor/Person/PersonnelGrant/PersonnelPolicy/PersonnelRequest/PersonnelSnapshot 与 prepare_personnel；任务get先行，tenant/user授权与目录解析、真实关系、厂区/类别/能力grant及单来源选择后冻结canonical请求与完整lease。资质objects只为承包商，培训/准入只为人员。

external_inquiry_personnel.check_external_personnel 独立装配沿原设备循环限额、去重、引用、可用性与trace规则；执行仍使用原 build_dynamic_definitions → ToolPolicy → ToolExecutor → SDK → bind_evidence → SQL023 发布。没有新增call/session接口、迁移、普通对话入口或授权写入。沿用原通用 ScriptedDynamicToolModel，未为同协议复制dynamic_personnel_model.py。独立循环重复是设计已接受的代价；后续抽公共核心另审。

报告包含人员/承包商/类别，status=awaiting_review，summary_status=unverified_candidate。completed只表示本轮观察齐全；不批准进场或合规。unknown/partial/unusable与原始状态分别保留；无自动翻页、切备用来源或重试。

## TDD与审查证据

- 人员路由初始RED：20 failed，均为模块缺失断言；新增实现后20 passed。
- 工作流初始RED：1failed/23errors/1passed（模块缺失造成fixture setup错误）；后收敛单例明确断言personnel workflow missing，装配后两文件45 passed。
- 独立只读审查发现grant存在对象负例及合法Schema参数篡改覆盖不足。补入四种存在对象但grant拒绝与原ToolPolicy/Executor真实人员快照篡改零handler/wire用例后，独立50 passed in5.62s；两Important关闭，无未解决Critical/Important代码问题。
- grant测试能力验证：临时仅移除本包人员/承包商grant条件，实际2failed/2passed（DID NOT RAISE）；finally按原字节恢复。随后50 passed in5.78s，JUnit pure-green.xml。该mutation证明新增用例能抓放权，不把测试通过冒充模型选择质量。
- 独占六Python文件Ruff All checks passed；早期53/55项格式错误经仅自有文件fix/format关闭，最后提示词长行拆串关闭。

## 环境失败保留

真实SDK/PG前最初normal单例1failed与五例5failed均在registry.initialize处storage_unavailable，尚无业务SDK wire。核查既有PG未运行；首次pg_ctl未显式端口，默认5432绑定Permission denied；随后显式127.0.0.1:55432启动原完整PG17集群，崩溃恢复fsync持续推进。Start-Process -Wait等待后代导致wrapper未退出，取消该wrapper也结束了刚恢复的子服务器；因此另一次五例5failed仍为storage_unavailable。修正为隐藏且不Wait的启动helper后既有集群再次恢复并ready，再开始SDK测试。未initdb、删库或改系统PG10；没有提高产品超时、增加自动重试或用成功覆盖这些环境失败。

本次使用本机既有隔离 anlan_mcp_20261116_v2 测试库，凭据仅在环境/进程内，未打印。启动日志在私有.runtime/engineering-20261122-dynamic-business/pg-start.log。SDK/PG结果以最终追加段为准。

## 文件与交接

新增自有：src/anlan/tools/dynamic_mcp/personnel.py；src/anlan/workflows/external_inquiry_personnel.py；tests/test_dynamic_mcp_personnel.py、personnel_inquiry.py、personnel_e2e.py；tests/fixtures/dynamic_mcp_personnel_server.py；examples/synthetic/dynamic-mcp-v1/personnel/README.md；本包design/plan/report与最终manifest。

零真实模型请求；无SSH/部署、stage/commit/reset/clean/切分支。总文档、部署文件和冻结核心不改。回退由总窗口先停入口/禁用本包服务，再撤明确新增文件；保留注册历史/调用审计，不降generation、不DROP表、不复活旧lease。源码/制品/线上版本记录由总窗口统一集成发布完成。

真实企业、生产TLS/IAM、真实模型自主选择质量、普通对话装配、作业票、历史双源和自动分页仍待后续独立包。首包只读合成工程通过不升级个人掌握或整个P10验收。

补充失败：PG就绪后五例进入真实发现，但测试装配有一处旧service_id="equipment"未随注册名"personnel"替换，registry.get正确拒绝access_denied（5failed in28.08s，e2e-service-id-red.xml）。已仅修正自有测试service_id，未放宽注册库权限，重新运行人员SDK场景。

## SDK首轮实际结果

五个真实本地stdio SDK+PG+scripted端到端场景：5 passed in95.13s，0失败/错误/跳过，e2e.xml。每场景实际3次tools/call、3条SQL023审计，查询时间与UTC接收时间分开，原任务完全不变。正常返回active资质/completed培训/denied准入且候选含denied；partial_empty保留三partial与unknown；unknown保留不可用。wrong_category仅资质/培训失败，准入请求category=None因此第三条有效；wrong_object三条均失败。

独立E2E审查确认对象与receipt映射正确，无新增生产代码问题；建议补精确data_error断言，区分绑定拒绝与调用后timeout。该测试增强将在当前串行回归结束后单独执行，最终验收以前述新增断言通过为准。

## 首轮串行Gate与增强

21文件、338项串行回归实际335passed/3failed in373.91s，serial-gate.log/xml保留。三失败均为本包SDK正向场景：normal在discover为connect_timeout；partial三attempt均timeout、实际仅1次wire；unknown首调用timeout（wire计入），后两条missing未知有效返回。不是合同类别错乱或权限放宽。已复制pytest-746的本包trace到私有证据目录，与早先五项单独通过的pytest-745 trace分开。

wrong_object旧测试有一次把timeout当通用missing_evidence容纳，独立审查提出的精确类别断言有必要。已补每条报告reason=data_error/evidence_valid=False及PG receipt.error_code=data_error，wrong_category精确两失败一有效，wrong_object三失败，其他场景要求全有效；任何timeout都不能以合同拒绝通过。

人员夹具原从设备参考复制的HTTP分支和StreamableHTTPSessionManager导入完全未在本包使用，现删去，明确仅stdio（不声称人员HTTP已验）。冻结产品源码/时限不变。最终串行复验使用-u日志及时输出与本进程临时Windows防空闲请求；仅线程执行状态，无电源计划/全局系统配置修改，进程结束自动失效并正常路径显式释放。最终结果待追加，不用重复跑到绿来隐藏前轮失败。

## 最终验收与交协调窗口

最终21文件338项串行运行：**334 passed、4 failed，367.70s，exit1**。由final-gate.xml逐testcase复核，**本包人员55项全部passed、0失败/错误/跳过**，包含增强后的真实SDK/PG五场景；临时线程防空闲请求已显式released=True。没有真实模型调用。

四项未通过均在冻结已有文件：
- test_dynamic_mcp_device_e2e 正常设备链：missing_evidence，不能把该观察记作完整成功。
- test_dynamic_mcp_execution 的实际在飞撤权 disable/refresh/replace 三参数：await task时抛TimeoutError，未到预期撤权异常。未擅自放宽时限或修改这些测试/实现。

本窗口不能宣称完整受影响回归通过，也不把四项旧链失败无证据归因于人员增量或单一环境原因。最小复现为本包run_gate.py同DSN运行上述四节点；完整失败栈在final-gate.log/xml。已有截止/启动波动有证据，但四项最终根因与复验由总窗口在冻结核心所有权内协调。本包未提出必须变更共享接口的结论。

本包新增人员首链与独立审查已完成，可交总窗口复验；**整体集成/发布门禁仍待上述四项复核，不能据本报告自动发布**。人员实际SDK机制、scripted协议与真实PG证据分开，不声称真实模型/企业可用性。11个冻结核心/SQL校验值最终与本包验证基线完全一致。证据计数见evidence.json，文件SHA见owned-files.json。

本窗口已停止所有测试和开发，既有本地PG保持运行供总窗口复验；无本包SDK后台调用。随后仅完成报告/manifest与静态校验，不重复整包跑到绿。无SSH/部署/提交；统一集成发布由总窗口处理。
