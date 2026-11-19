# M1 动态 MCP 合同（无 runtime）

`contracts.py` 提供 dynamic-registration-v1 / dynamic-evidence-v1，能力合同版本 1：

- equipment.asset / inspection / fault.query
- contractor.qualification.query、person.training.query、person.access.query
- permit.ticket / overlap.query

所有模型可调用 `model_json_schema()` 导出结构 Schema；实际校验必须使用 Pydantic 合同（包含 capability 与载荷匹配、范围、分页、有效期等交叉字段校验），不能仅检查 JSON Schema。类型化载荷保留 original_status；没有映射的状态使用 unknown，不能猜为有效。

`CapabilityRequest` 只含业务对象、厂区、时点、可选 category/窗口/cursor；资质和培训必须提供 category，票据必须提供窗口。身份由宿主装配，不接收模型身份。`bind_evidence` 验证能力/版本/对象/厂区/查询时点/窗口/类别。

`DynamicEvidence` 只接受远端字段。`HostReceipt` 独立保存服务、工具、调用、接收时间、配置/目录/路由版本、选源原因和摘要，禁止通过展开远端字典覆盖宿主数据。ENTERPRISE_DECLARED 是来源自述，不是认证。

`usable` 仅代表完整且有版本/当前来源的观察：不完整分页、缺来源、未来来源、缺有效期、业务有效期缺失或过期均为 false；不代表没有风险、批准或真实来源认证。完整空列表仍须来源与完整覆盖，不能由截断结果推断无风险。sources 的 record_id 可为空以显式表示汇总来源缺少记录定位；业务记录则必须在 sources 中找到 record_id。

`examples/*.json` 为三个场景的合成注册声明。state 字段是合同数据，不授予执行权。连接只保存 executable_ref/target_ref/credential_ref；`validate_targets` 必须接收宿主独立维护的受信 executable 集合、精确 argv profile 和 HTTPS 目标。样例不附真实可执行文件、凭据或服务，无注册管理/连接发现/启停/SDK 生命周期/来源路由/模型动态执行。

本包不实现跨来源竞争的自动选择，也不把 readonlyHint 或描述提升为授权。后续 M2/M3 仍须独立管理身份、Schema 子集门禁、启停复验与迟到结果拒绝；所有执行只能经本地 Registry/Policy/Executor。
