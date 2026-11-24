# 企业自定义 MCP 接入（注册与设备首链）

更新：2026-11-18。此指南对应当前实现；[M2报告](../phases/engineering-20261116/dynamic-mcp-registration-report.md)记录注册与SDK/PG测试，[M3报告](../phases/engineering-20261116/dynamic-mcp-inquiry-report.md)记录设备三能力首链。注册、发现与受控设备调用已有本地有限验收；启用服务不使现有普通对话自动获得新工具，普通对话/操作台装配仍是后续增量。

## 两层接入合同

协议层使用当前锁定的官方 MCP SDK，受控stdio或Streamable HTTP。业务层必须实现本地八项能力中相应版本合同：设备台账/检验/故障、承包商资质、人员培训/准入、作业票/交叉作业候选。`src/anlan/tools/dynamic_mcp/contracts.py`定义CapabilityRequest、DynamicEvidence及载荷；`catalog.expected_schemas(capability)`提供首版精确Schema profile，实际返回仍必须经过本地Pydantic及bind_evidence交叉字段验证。

外部原工具名与能力名无需相同，带点原名逐字保留，宿主生成模型可用alias并检查碰撞。首版要求inputSchema/outputSchema与本地profile规范化后精确一致；自由文本输出、未知关键词、远程引用、循环或过深Schema不会启用。readonlyHint与描述不授予权限。

结果必须携带能力/版本、明确对象与厂区、带时区查询时点、来源版本/更新时间/有效期、完整性/分页/覆盖范围。unknown/error/partial不得变成“安全/有效/无故障”。服务自述ENTERPRISE_DECLARED不是来源认证；宿主接收时间和摘要不冒充原始更新时间。合成注册样例位于`src/anlan/tools/dynamic_mcp/examples/`，不包含真实凭据或自动启动授权。

## 管理入口

```powershell
uv run --no-sync python -m anlan.interfaces.mcp_registry_cli --help
```

独立管理身份来自宿主控制的`ANLAN_MCP_ADMIN_POLICY`与`ANLAN_MCP_ADMIN_TOKEN`。策略保存purpose、subject、tenant_ids、actions、policy_version与令牌SHA256；令牌不放argv或注册JSON。普通业务Bearer、安全管理人员角色不会自动成为MCP管理员。持有本地源码/策略文件写权限或数据库管理权限的OS操作者属于宿主信任边界，本地入口不是生产IAM。

先由宿主设置可信数据库环境并初始化基础schema，再执行独立`initialize`应用新增SQL022；旧主initializer不隐式启用MCP。注册文件、受信targets和凭据映射分开管理：连接只引用executable_ref/target_ref/credential_ref，真实URL/固定argv/凭据环境映射由宿主策略提供。

使用`register → discover → inspect → enable`。修改命令需要独立command-id，除首次注册外使用当前expected-generation；enable还需inspect得到的validation-digest。相同命令及载荷幂等，不同载荷复用ID拒绝。调用`--help`或各子命令`--help`查看精确参数；不要复制历史generation或未知验证摘要。

replace/refresh先使旧目录失效，重新发现/验证后仍需显式enable；失败保持停用。disable提交后旧lease不能新分发或发布迟到结果。进程中断的网络操作保留unknown，不自动重复请求。启用同企业/能力/厂区的竞争来源会被拒绝，M3首包只接受明确单源，后续历史分工/双源关系需另行配置合同。

## 受信传输边界

stdio使用宿主固定绝对可执行路径、精确argv与cwd，拒绝自由shell表达式；不继承任意模型/业务密钥。SDK stdio reader缺少解析前单行上限，因此仅运行受信程序，不把该接口当不可信插件沙箱。

HTTP首版只开放明确登记的IP字面量HTTPS目标（证书须匹配IP），禁重定向、环境代理、任意URL与自动OAuth。SYNTHETIC测试才可使用显式登记的127.0.0.1 HTTP例外。实际请求逐次检查目标，解析前限制响应流并拒压缩编码；业务结果另受64KiB合同限制。域名/DNS重绑定适配、生产证书与真实企业系统仍待独立验证。

M2生产运行时只初始化和发现，不提供绕过本地执行器的diagnose/call命令。M3业务入口位于`workflows/external_inquiry.py`的`check_external_inquiry`，由可信宿主注入任务服务、身份、InquiryPolicyConfig、注册库、ExecutionHost和模型。设备asset/inspection/fault三能力由任务目录进入同一本地Registry/Policy/Executor，再经内部SDK适配与PG审计发布二检。模型与工具返回不能改身份、对象授权、目标、凭据或目录版本。首链验证使用scripted和真实本地SDK，不证明自然语言自主选源质量。

## 验证与回滚

定向入口为`tests/test_dynamic_mcp_contracts.py`、catalog/registry/cli/runtime/integration测试；PG须显式隔离DSN，真实SDK、本地替身、真实模型与企业系统证据分开。当前没有真实模型选工具效果或生产认证结论。

先禁用服务并关闭所属会话，再撤宿主引用/代码入口；保留注册历史、不可变审计及撤权代次。不降低generation、不复活旧目录、不自动DROP表，不回滚旧SQL或其他窗口改动。管理失败/数据库不可用必须报告失败，不能声称禁用已经提交。
