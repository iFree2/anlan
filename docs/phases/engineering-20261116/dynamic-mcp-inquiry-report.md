# M3 动态设备首链实施报告

日期：2026-11-17。依据dynamic-mcp-inquiry-design.md最终D约束，设备asset/inspection/fault三能力，scripted零付费+真实本地SDK；不宣称真实模型自主选择质量。

## 实施检查点

- [x] routing/Policy：可信企业厂区别名、对象授权、单来源冲突拒绝，冻结snapshot与同TaskCatalog。
- [x] execution/023：只在本地Executor handler内SDK call、三种时钟、M1绑定、head代次/禁用发布二检、真实PG审计。
- [x] workflow/model：跨轮seen call_id、attempts与wire各6硬限、候选引用/partial/unknown、trace与原状态不变。
- [x] 根集成/审查/旧链与Ruff最终验收。

所有权：routing worker仅routing.py/policy.py及routing测试；execution worker仅execution.py/registry.py新增方法/runtime内部helper/新增023及execution测试；workflow worker仅external_inquiry.py/dynamic_tool_model.py与inquiry测试。root拥有新三能力SDK fixture、集成测试、报告及经RED证明必要的Executor最小兼容修改。均明确并发不回退、无stage/commit/分支/窗口/云/live。

已实际观察：`uv run --no-sync pytest -q tests/test_dynamic_mcp_executor_binding.py` →1failed，datetime参数被旧Executor判outside_references；input参数改为model_dump(mode='json')后复验。该改动不放松参数合同，只将同一合法参数表示归一到任务grant的JSON表示。固定人员/区域/知识输入均原为字符串，旧结果与限额不变。

## 真实检查点与排查证据

- datetime规范化修复：新增binding测试RED1failed→新旧Executor共10passed。没有放松旧合同。
- routing首批17passed，随后含T1回归54passed；保留原任务correlation_id的断言实际RED/GREEN。
- workflow/model14个fake边界与旧31合计45passed；覆盖跨轮重复ID、attempt/wire上限、第7次零分发、query_at注入、引用与receipt_call_id映射、partial/unknown/无来源警示、模型耗尽deadline转loop_timeout。
- execution已报告真实stdio三能力与负例6passed、取消测试selected GREEN，纯PG/冻结lease/严格授权/预算8passed；发布共享锁与disable受控交错2passed（先publish则disable等待，先disable则发布拒绝不插入）。这些阶段结果不是整包最终验收。
- root真实PG+SDK+scripted E2E仍未通过：曾一次M2 discover connect_timeout，保留为环境/启动失败，没有提高产品5秒限额；后串行诊断确定三个data_error根因为execution已读取snapshot.leases而routing尚未新增该字段，异常为AttributeError、发生在SDK业务wire前。已要求routing完成模型前冻结lease接口，并在execution比较当前lease全字段，不能默默接受新凭据代次。不得把重复跑到一次绿当作修复证据。
- 独立审查明确取消后清理可能增加墙钟耗时：工作/分发/发布deadline仍按5秒handler及60秒父monotonic阻断，SDK资源回收有独立最多3秒清理窗口；最终报告不得宣称总墙钟严格<=5/60。调用取消不退款、不自动重发；待实际清理验收。
- 原worker发生额度中断后按父指令在同worker恢复，不换模型、不新建窗口、不回退。所有待验代码和RED保留。

本段是未完成检查点，不是完成声明；以最终追加的整包结果为准。

## 根因收敛与审查修复

root接管routing的最小leases接线前已中断原routing worker并明确所有权移交，没有并发覆盖。新增“模型前冻结凭据lease”用例实际RED AttributeError→routing全23passed；prepare逐entry resolve_business捕获lease并严格比较目录代次/策略，execution第一次及后续分发都与snapshot lease一致。

完整链随后GREEN1 in10.80s。保留trace进一步确认上一轮无异常但missing_evidence是第一项工具5.059秒截止、实际wire_calls=2，后两项ok；不是错误时点/合同已通过却丢失，deadline按设计拒绝第一项缺证。原始trace复制到`.runtime/engineering-20261116/m3-prewire-timeout.trace.jsonl`。未修改产品期限、未加入自动重试，也不将该失败抹掉；冷启动/负载仍可能触发截止并返回缺证，此为真实限制，不声称所有环境稳定达标。

根集成测试已去除临时diagnostic wrapper，最终会重跑无诊断装配原链，并检查三条真实PG receipt与报告receipt_call_id完全一致。

失败分类TDD：Executor原将RuntimeFailure(disconnected)汇总data_error，新增用例真实RED；引入仅固定宿主类别的ToolExecutionFailure，RuntimeFailure继承，Executor专门捕获保留code且evidence_valid=False。新旧Executor合计11passed。原始Exception仍data_error；取消传播；未把失败提升为有效来源。

独立审查及workflow补充均真实RED/GREEN：M1.usable驱动unusable_capabilities和unknown（observed/合同有效不变）；无知识工具时拒任何非空knowledge_citations；模型返回/候选发布/最终return显式monotonic，准备与每轮模型前亦有闸门；32KiB模型上下文超限保留观察且不再调用模型。workflow独占最终25项+旧31共56passed。父窗口独立纯复验47passed（当时collect）并关闭三项important，未运行SDK/PG，未混称协议结果。

023已在本包隔离v2库显式初始化，未改旧迁移/主initializer。新增业务resolve不借管理员身份，reader/tenant/服务enabled/代次/credential策略均再验；发布在head FOR SHARE锁内重验authority再插入，不持锁做网络。失败wire审计只存固定错误码/evidence_valid=False与宿主metadata，无远端正文；撤权代次变化拒绝发布，仅保留workflow拒绝trace。

## 执行层最终交付与限制

执行worker已冻结并停止全部SDK测试，独占源码不再改动。真实PG在飞disable/refresh/replace三模式均通过：实际tools/call发出后改变head，取消通知引用实际wire ID，零有效结果/审计发布。独立PG锁交错与lease/credential/授权重检均有回归，不借普通业务身份作管理员。

执行+M2 runtime曾52passed in83.43s；最后审计标记修改后的execution为27passed/1 startup timeout，原失败保留。定向正常三能力+取消2passed in7.47s；cancel→handler返回实测0.005秒、PID已退出。timeout日志显示前两会话initialize/list/call完成，第三会话在started事件写入前耗尽4.8秒，属于冷启动/import截止；不视为证据绑定错乱，也不声称彻底消除冷启动波动。

新增真实HTTP三能力、wire_calls=6、第7次零wire；schema drift零业务wire；wrong_object/time/capability/oversized/is_error/disconnect拒绝；缺来源与partial_empty不能成为usable。失败wire审计仅固定code；没有原始响应时response_hash_available=False，不能把空串SHA当作真实响应哈希。wire_sent是每handler本地标记，避免共享预算时混记其他调用。

工作截止和资源回收分别说明：5秒handler/60秒父预算使用monotonic，超时后停止新wire/发布；取消仍可进入独立最多3秒的清理窗口，总墙钟不承诺严格<=5/60。真实OS清理失败尚未人工注入，cleanup_failed分支未称真实故障验收；stdiosdk预解析无限行、生产TLS/企业服务等M2限制继续保留。

本包没有真实模型调用；scripted协议效果、真实SDK机制、真实PG事务和未来真实模型选源效果分别记录。首包仅设备三能力，人员/票据合同保留但未实现其端到端；不实现自动分页/跨源关系/企业认证部署。

## 文件与回滚

新增routing.py、execution.py、external_inquiry.py、dynamic_tool_model.py、023_dynamic_mcp_calls.sql、对应routing/execution/inquiry/device_e2e/executor_binding测试及三能力合成SDK fixture；小幅Policy可信grant入口、Executor JSON参数归一/固定失败类型、M2 registry业务resolve和runtime内部会话helper。M2公开管理入口仍无call/diagnose，不导出ClientSession。旧ToolResult Literal与旧SQL均未修改。

无stage/commit、切分支、云、部署或付费调用；没有覆盖其他窗口修改。回滚先停止inquiry装配/禁用服务、关闭会话，再人工撤本包新增源码和T1自有新增方法；保持M2撤权代次，不自动复活旧目录或降generation。已应用023调用审计默认保留，不DROP历史表/数据库，不用reset/clean整体恢复。主initializer装配由父窗口独占。

最终整包结果随后追加，本报告不将中间失败静默删除。

## 最终一次串行 Gate（源码冻结后）

2026-11-17，全部worker释放SDK后执行一次：以本包显式隔离DSN指向anlan_mcp_20261116_v2（凭据仅内存注入、不输出），Python展开`tests/test_dynamic_mcp*.py`全部文件，再追加旧`test_tool_registry.py/test_tool_executor.py/test_tools.py/test_tool_loop.py/test_tool_model.py/test_knowledge_tool_loop.py/test_business_bridge.py`，运行`uv run --no-sync python`内`pytest.main(['-q', *files])`。

**实际277 passed in163.81s，exit0，无fail/error/skip/warnings。** 包含M3新增79项与原T/M2定向198项，真实本地stdio/HTTP、真实PG发布/撤权并发、scripted三能力根链与三条PGreceipt映射均在同一串行Gate通过。没有在此Gate失败后自动重跑，原开发中失败仍在上文及trace保留。

最终`uv run --no-sync ruff check src tests scripts evals` → **All checks passed!**，exit0；本包`git diff --check`无输出exit0。

独立审查状态：父integration_review纯复验的来源可用性、伪知识引用、同步deadline三项important均关闭；worker交叉审查的任务前lease、强制宿主授权、scope/credential二检、发布锁、失败分类与审计已落实测试。冷启动截止和额外清理窗口保留为实际限制，不以通过结果抹除；未验证真实企业/生产TLS/真实模型效果，不代签父窗口整仓非live与wheel门禁。

M3设备首包已形成可审查闭环，四项实施检查点完成，**源码已冻结，可交父窗口启动整仓独立回归及wheel验证**。本窗口不再修改执行源码，不扩大下一包；无未解决已复现critical/important。
