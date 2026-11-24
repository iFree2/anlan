# M2 动态 MCP 注册、管理与 SDK 生命周期详细设计

日期：2026-11-16。状态：**最终D审查通过，按本文件末尾修订约束进入TDD实施。**

依据：`docs/superpowers/specs/2026-11-16-engineering-evolution-design.md`、总实施计划、P10 plan/acceptance 和本包 `tools-mcp-report.md`。本轮应用 brainstorming / writing-plans 的设计分解与自审流程，文件位置、禁止 commit 和先 D 审查再实施遵循本次明确指令。T1/M1 已交付，最后定向 118 passed；该数字不是 M2 验收。

## 1. 范围与方案

M2 交付：可信本地管理 CLI、PG 注册版本与诊断持久化、受控 stdio / 受信 Streamable HTTP 的真实官方 SDK 初始化/发现/取消/关闭、严格 Schema 门禁、显式启用/禁用/刷新，以及按可信租户和能力过滤的不可变目录。

M2 不装配普通 HTTP/Bearer 管理权限、不发布模型可调用动态工具、不实现厂区别名解析或来源竞争选择、不连接业务工作流。M3 才把动态调用接入 T1 Registry/Policy/Executor 并完成来源路由；M2生产代码没有diagnose、call_tool或返回原始ClientSession的公开入口。现有固定 Java/HTTP/MCP 与工具循环保持原入口。

比较三个方案：

| 方案 | 代价与判断 |
|---|---|
| 直接修改 ServiceConfig/Bearer 与普通业务入口 | 改动面大，管理权限易混用；本包不选 |
| JSON 文件保存注册并在进程内启停 | 简单，但多进程版本竞争、撤权和审计恢复不足；不选 |
| PG 不可变版本、服务头 CAS、独立 CLI、短生命周期 SDK 会话 | 可恢复、可审计且可先独立验证；采用 |

本轮先支持**每次管理操作独占会话**。不建连接池/守护进程；每次发现打开会话、完成后关闭。免去长驻跨版本会话复用风险，后续 M3 按目录租约连接。

## 2. 已核对的本地基线

2026-11-16 在当前环境只读核对：Python 项目声明 3.13；`uv run --no-sync python` 读取包元数据，实际 `mcp==1.30.0`、`jsonschema==4.26.0`。`uv.lock` 已锁定这两包，M2 不升级依赖、不借此修改锁文件。

已读取 SDK 安装源码与签名：

- `ClientSession(read_stream, write_stream, read_timeout_seconds=..., ...)`；`initialize()`、`list_tools(cursor=...)`、`call_tool(name, arguments, read_timeout_seconds=...)`。
- `stdio_client(StdioServerParameters(...), errlog=...)`；参数支持 command/args/env/cwd。关闭先关 stdin、等待退出，再按平台终止进程树，最终关闭流。
- `streamable_http_client(url, http_client=..., terminate_on_close=True)`；传入自有 HTTP client 时 SDK 不负责关闭它；宿主须拥有 client 生命周期。
- SDK 的 HTTP 同源重定向由其 transport 自己决定，不受 httpx `follow_redirects` 开关完整控制。宿主 HTTP transport 必须检查**每个实际请求**，拒绝未登记 URL/Origin、重定向及地址变化。
- SDK stdio stdout reader 在 JSON 解析前累积行，公开 `stdio_client` 没有单行字节上限。M2 的发现/结果大小约束是解析后的合同上限，不能声称能防御恶意已许可本地程序的无换行 stdout 内存攻击。只运行受信固定 executable+argv；恶意程序沙箱/OS资源限制不属于本轮。此限制须保留在验收报告。

现有持久化用 psycopg.AsyncConnection、`conninfo()`、`anlan_v2`、显式初始化与事务。已有 SQL 最大号 020；021 为另一设计预留，M2 **建议新增 022_dynamic_mcp.sql**，实施时再检查占用；不改旧 SQL。主库 `initialize_database` 的装配由主窗口独占，不在本包改。

## 3. 文件所有权与精确接口

新增文件：

| 文件 | 职责 |
|---|---|
| `src/anlan/tools/dynamic_mcp/registry.py` | 管理授权合同、PG head/revision/discovery/command、CAS/幂等、诊断状态；不启动进程 |
| `src/anlan/tools/dynamic_mcp/runtime.py` | 可信目标解析、credential resolver、独占 SDK 会话、超时/取消/关闭、发现诊断；不直接写DB，不导出业务调用 |
| `src/anlan/tools/dynamic_mcp/catalog.py` | 发现合同/Schema 比较/别名/冻结目录与租约、按 scope 过滤；不做业务来源选择 |
| `src/anlan/interfaces/mcp_registry_cli.py` | 独立 `python -m` CLI，验证可信管理上下文、调度上述模块，结构化脱敏输出 |
| `src/anlan/sql/022_dynamic_mcp.sql` | 仅本包新增表/索引/不可变触发器；由集成窗口确认号与装配 |
| `tests/test_dynamic_mcp_registry.py` | PG 事务/幂等/并发/跨租户/管理拒绝 |
| `tests/test_dynamic_mcp_runtime.py` | 官方SDK stdio + HTTP真服务、发现/取消/关闭/传输许可，测试专用合成call |
| `tests/test_dynamic_mcp_catalog.py` | Schema、过滤、版本、别名与禁用租约 |
| `tests/test_dynamic_mcp_cli.py` | 独立管理入口/输出/错误码/凭据不泄露 |
| `tests/fixtures/dynamic_mcp_server.py` | 仅合成真实协议服务，正常/分页/坏 Schema/慢调用/关闭诊断模式 |

允许小幅扩展 M1 `contracts.py` 仅在审查确认必要时；优先将 M2 合同放在三个新模块，避免影响 M1 返回合同。报告另存 `dynamic-mcp-registration-report.md`。不改 T1 执行器/模型/循环、service_config、api、普通 cli、pyproject、总文档或原测试。

接口使用 frozen dataclass 或 frozen StrictModel，集合用 tuple/frozenset，返回对象不含密钥：

```text
registry.py
  AdminPrincipal(subject, tenant_ids, actions, policy_version)  # 由独立认证边界产生
  ManagedRegistration(registration: Registration, owner_subject, reader_user_ids)
  ServiceHead(tenant_id, service_id, generation, config_revision,
              state, discovery_id?, validation_digest?, target_policy_version)
  CommandReceipt(command_id, action, generation, status, error_code?)
  DynamicMcpRegistry(dsn, admin_authorizer, clock)
    initialize(admin) -> None
    register(admin, managed, command_id, expected_generation=0) -> CommandReceipt
    replace(admin, service_id, managed, expected_generation, command_id) -> CommandReceipt
    record_discovery(admin, lease, discovery, command_id) -> CommandReceipt
    enable(admin, service_id, expected_generation, validation_digest, command_id) -> CommandReceipt
    disable(admin, service_id, expected_generation, command_id) -> CommandReceipt
    get/list(admin, tenant_id, limit<=100, cursor?) -> 脱敏 head + revision + 最后诊断
    reconcile(admin, command_id, expected_operation_status="reserved") -> CommandReceipt
    load_catalog(scope: CatalogScope) -> CatalogSnapshot
    assert_current(lease: CatalogLease) -> None

catalog.py
  CatalogScope(identity: Identity, capabilities, factory_ids)  # 可信宿主注入；不能由模型构建
  DiscoverySnapshot(discovery_id, captured_generation, protocol_version,
                    server_name, server_version, discovered_at, tools, digest)
  ValidatedTool(original_name, alias, capability, contract_version,
                input_schema_digest, output_schema_digest, schema_profile)
  CatalogEntry(tenant_id, service_id, config_revision, generation,
               discovery_id, alias, original_name, capability, contract_version, factory_ids)
  CatalogSnapshot(catalog_id, tenant_id, reader_user_id, entries, created_at)
  CatalogLease(tenant_id, service_id, generation, config_revision, discovery_id,
               target_policy_version, credential_generation)
  validate_discovery(registration, snapshot) -> ValidationReport
  build_catalog(scope, current_heads, validated_snapshots) -> CatalogSnapshot

runtime.py
  TrustedTargets(policy_version, executable_profiles, http_profiles)
  CredentialResolver.resolve(tenant_id, credential_ref) -> SecretStr + credential_generation
  RuntimeManager(targets, credentials, registry_guard, clock)
    discover(admin, registration, lease) -> DiscoverySnapshot
    close() -> CleanupReceipt
```

管理 authorization 检查先于 DB 存在性查询、进程启动、DNS/HTTP 或 credential resolve。`assert_current` 走当前权威 DB，不信旧目录的 enabled 字段。M2不提供任何生产业务调用方法或会话句柄。生产runtime只负责initialize/list_tools及对应取消/关闭；任何动态业务call必须等M3经本地Registry/Policy/Executor。

## 4. 管理身份与宿主信任

普通 `Identity`、ServiceConfig.TokenGrant、协作 safety_manager 角色均**不能**转换成 AdminPrincipal。不添加 HTTP 管理路由，不改变普通 Bearer 的解释。

首版独立 CLI 从宿主注入 `AdminPolicy`（独立受控配置）与 `ANLAN_MCP_ADMIN_TOKEN` 认证：令牌格式为 `mcpadm_` 加32字节随机值的64位hex编码，配置仅保存完整令牌的 SHA256、purpose=`dynamic_mcp_admin`、subject、tenant_ids、actions、policy_version；比较使用恒定时间。环境值不传 argv、不打印。配置路径由可信宿主环境 `ANLAN_MCP_ADMIN_POLICY` 指定，CLI 没有 `--admin/--role/--user/--token/--policy` 自助扩权参数。注册 JSON 的 owner_subject/tenant 不能授予角色；owner_subject 必须等于认证 subject 或由授权策略明确许可。

这是**本地宿主进程信任边界**：能任意修改管理策略文件/宿主环境/本地代码或直接使用 DB 管理账号的 OS 操作者已在信任内，M2 不声称对其提供隔离。策略文件必须由宿主运维控制写权限；本轮不新增生产 IAM、Windows ACL 管理或远程管理员登录。普通 HTTP Bearer 字符串即使格式相同，也不查询普通 TokenGrant；未独立登记为管理用途则拒绝。严禁把普通配置文件当作 AdminPolicy。

actions 固定：`schema_initialize`、`register`、`replace`、`discover`、`enable`、`disable`、`refresh`、`inspect`、`reconcile`；默认缺 action 拒绝；每次操作和网络返回发布前重检认证有效性/tenant/action。M2 管理策略更换由宿主文件重新读取；发现/启用时policy_version 必须一致，变更后旧操作 lease 失效。

`reader_user_ids` 为显式精确业务读者集合，缺失/空集合不发布给任何业务用户；不在 M2 实现角色推导。目录过滤同时要求 Identity.tenant_id 相等、user_id 在该集合、请求 capability 交集、factory_id 交集、head enabled、对应发现已验证且版本一致。无权/缺记录均返回空目录/统一 access_denied，不泄露服务存在性。scope 由未来宿主路由传入，M2 没有普通用户可自填 scope 的网络入口。

## 5. 可信目标、凭据与副作用边界

注册只含 M1 的 executable_ref 或 target_ref 与 credential_ref，配置正文无 URL/命令正文/密钥。宿主 `TrustedTargets` 与注册记录分离，由 AdminPolicy 指向的可信配置加载。

stdio profile 固定：tenant、executable_ref、解析后的绝对可执行路径、**精确 argv 元组**、绝对 cwd、允许传递的 env 键集合、profile_version。执行用 StdioServerParameters 的 command/args，禁止 shell=True、cmd /c、PowerShell -Command、Python -c 等自由表达式 profile；允许 `python -m <明确模块>`，模块和参数精确固定。可执行文件不得从 PATH 按模型文字解析。注册 argv 与宿主 profile 完全相等（包含空格语义），不可经 strip 改写后再执行；对 M1 Text 的归一化差异，运行前使用原始 argv 字节/字符摘要比对可信 profile，不接受“归一后相同、原文不同”的 argv。禁止继承任意业务/模型密钥，env 仅显式 allowlist + SDK 最小系统环境；本地程序本身须受信。

HTTP profile 固定 tenant、target_ref、scheme/host/port/path 的精确 URL、允许解析 IP 集合、TLS 验证设置、profile_version。正常 profile 仅 HTTPS，无 username/password/query/fragment，禁止重定向；不使用环境代理 `trust_env=False`，无自动 OAuth 或自动外联注册。实际连接地址必须等于profile中登记的IP字面量；不接受需要DNS解析的host。M2首版只开放管理员登记的IP字面量HTTPS目标，证书必须含对应IP SAN；域名profile返回unsupported_target，不先实现自定义DNS backend。单纯`getaddrinfo`后仍让httpx再次解析**不满足**防重绑定要求，域名支持留后续独立增量。每次传输请求检查 URL，包括 SDK 重定向、GET stream、DELETE 终止会话；任何偏离目标路径或状态 3xx 均拒绝，不能只设 follow_redirects=False。

真实本地 HTTP 测试使用明确隔离的 `synthetic_loopback_http=True` profile：只允许 SYNTHETIC、127.0.0.1、测试动态端口与固定 `/mcp` 路径，不允许 `localhost`/任意地址；该开关不能从注册 JSON 或普通用户请求获取。生产 HTTPS 证书/网络连通没有真实环境时单列未验证。

凭据在 resolve 时绑定 tenant/ref/generation；resolver 是宿主接口，首个本地适配可从明示环境变量取得 SecretStr，不落 PG。HTTP 仅发送到对应目标的 Authorization，stdio 仅传 profile 指定 env 名，不传命令参数。日志/异常/DB 只保存 credential_ref、generation、错误类别；禁止记录 headers、env 值、远端原始异常、stderr/stdout 正文或未审查 server description。

不根据服务描述/readonlyHint开放执行。M2只检查发现的业务Schema，不发出任何生产tools/call。真实call_tool仅存在tests内的合成协议测试，使用固定合成fixture，不能导入或暴露为生产管理功能；其测试结果不构成业务证据。

## 6. 持久化、版本与并发

建议新增独立 `022_dynamic_mcp.sql`，表全部限定 `anlan_v2`。初始化由 `DynamicMcpRegistry.initialize(admin)` 显式执行，需 schema_initialize 权限、基础 anlan_v2/anlan_schema_migrations 已存在、单独 advisory migration lock、整包事务；成功写 version=22。重复执行幂等，已有未知形状表或 migration hash 不符则 fail closed。不调用/改动主 `initialize_database`；集成窗口后续装配。

| 表 | 主键与关键列 |
|---|---|
| `dynamic_mcp_heads` | PK(tenant_id,service_id)；generation bigint>=1，config_revision>=1，state，discovery_id nullable，validation_digest nullable，target_policy_version，updated_at |
| `dynamic_mcp_revisions` | PK(tenant_id,service_id,config_revision)；registration_json，owner_subject，reader_user_ids JSON，config_hash，created_by，created_at；不可 UPDATE/DELETE |
| `dynamic_mcp_discoveries` | PK(tenant_id,service_id,discovery_id)；config_revision，captured_generation，tools_json，protocol/server version，schema_profile，snapshot_hash，validation_json，status，created_at；不可 UPDATE/DELETE |
| `dynamic_mcp_operations` | PK(tenant_id,admin_subject,command_id)；action、payload_hash、lease_json、status=reserved/completed/outcome_unknown、started_at、deadline_at；用于网络操作的持久化单次占位，不存正文 |
| `dynamic_mcp_commands` | PK(tenant_id,admin_subject,command_id)；action，payload_hash，expected_generation，result_json，created_at；不可 UPDATE/DELETE |

约束：head 指向同 tenant/service 的 revision/discovery；JSON object/array类型与大小有DB CHECK；discovery持久化只存工具名称、移除title/description/examples/$comment的规范Schema及宿主诊断；禁止保存SDK原始description、annotations自由正文或服务返回正文；配置上限 64KiB、每工具 schema 各 64KiB、发现总量 512KiB、最多 50 工具/10 页（分页遇重复 cursor、重复原工具名均失败）。注册绑定最多沿用 M1 30；目录别名不会导致静默截断。schema 解析后最大深度16、节点2048，超限拒绝验证。audit/command 不保存凭据正文、响应原文或自由 stderr。

`generation` 是宿主单调并发号；`config_revision` 只在更换注册配置/reader grants 时递增；M1 的 config_version 是人类标签，不能代替 CAS 号。disabled 后再 enabled 必须 generation 增大；不能重用旧租约。discoveries 和 commands 保留历史，没有“恢复某旧 head generation”接口。

每个改变服务配置/状态/发布指针的写操作先认证；enable先取下述排序scope锁再锁自身head，其他操作在事务内锁定 `(tenant_id,service_id)` head（首次注册用同 key advisory transaction lock），比对 expected_generation。失败 code=`version_conflict`，无部分写。成功 head generation+1、不可变记录、command receipt 同事务提交。幂等 command_id 相同 actor/tenant/action/payload_hash 返回旧 receipt，不重复网络或写；相同 id 不同内容为 `idempotency_conflict`。跨 action 的 command_id 也不能复用。generation由DB返回，不由CLI或远端生成。reconcile只终结operation，不改变服务head generation；不能因为审计写入而意外撤销其他有效租约。initialize也不改变任何服务head。

**网络命令先占位，再外发。** discover/refresh 在任何连接前用同一command key锁定/插入 `dynamic_mcp_operations`，写入payload_hash、lease与deadline，提交后才连接。相同key+hash已reserved返回in_progress、不再外发；不同hash直接冲突。网络完成后在短事务写不可变command receipt，并将operation置completed；两者同事务。超过deadline或进程崩溃的reserved由reconcile在CAS下置outcome_unknown，只能记录未知，不能用原command自动重发。新command显式重试发现须再次授权并重新获取lease。operation允许单向状态更新，禁止删除/改payload_hash；command receipt保持不可变。纯DB命令不需network占位。inspect保持只读；reconcile需独立action授权，仅处理同tenant且该principal自己创建、已超过deadline的operation，以CAS记录outcome_unknown，禁止重发。

**网络调用不持有 PG 行锁。** discover/refresh：先取 lease，执行网络，返回后以 captured generation/config_revision/target-policy/credential-generation 重检；只有仍相同且允许该操作才发布/入库。discovery.captured_generation用于这次提交前的CAS；提交成功使head generation递增后，当前目录按head.discovery_id指针关联该快照，不再错误要求captured_generation等于递增后的head generation。若禁用/替换/刷新已发生，返回 `stale_generation`，迟到结果不成为 validated/current，最多保存无正文的失败 receipt。

## 7. 状态机、刷新和目录发布

注册 JSON 里 state 是声明输入，`register/replace` 只接受 registered；即使声称 enabled 也不得直接启用。新服务 head=registered，revision=1，generation=1。

流程：registered → discovered（完整 list_tools 快照已保存）→ validated（Schema/绑定/目标/范围检查全通过）→ enabled（单独管理动作）。实现可在一次 record_discovery 事务保存 discovered 或 validated 状态，validation_json 必须说明每项检查，不能仅凭握手进入 validated。

- discover 仅接受registered/discovered状态；validated/enabled要重新发现必须先refresh。discover失败保留当前配置与结构化诊断，head不前进到validated。
- enable 要求当前 revision 的 validated discovery、固定 schema_profile、目标策略仍有效、凭据可解析但不持久化正文，validation_digest 与 CLI 指定相同。
- 来源竞争：M2 不实现替代/历史/双源选源。为防止提前发布不明确来源，enable 若同 tenant/capability/factory 范围已有另一 enabled service，拒绝 `source_conflict`。enable事务按排序后的(tenant,capability,factory)键取advisory transaction locks再检查竞争并更新head，防止两个服务分别持自身行锁而同时启用重叠来源。M3 引入关系合同后才能放宽；M2 允许把竞争服务注册/发现/验证，不能启用覆盖。
- refresh 先事务将 head 从 enabled/validated 置 registered、清 discovery/validation，generation+1，提交后才开始网络。所有旧目录立即失效；失败保持停用，不继续使用旧 discovery。成功建立新发现/校验快照后仍须显式 enable，**即使 Schema 未变也不自动重启**。
- replace 同 refresh 的撤权效果，另 config_revision+1；reader grant/目标/argv/credential_ref 改变均属于新 revision。
- disable 从任意已有 state 置 disabled，generation+1、清发布指针；重复 command 幂等。disabled只允许inspect或显式refresh，不能直接discover/enable；先显式refresh → registered → validated → enable。

`CatalogSnapshot` 只列 enabled head 的合格 bindings，无未绑定发现工具、raw credential/URL/argv、原始服务描述。对每条 `(tenant,service,original_name,capability,contract_version)` 用SHA256生成 `m_`+62hex 别名（共64字符，并保留完整原组与完整摘要作碰撞检测）；发现截断摘要相同但原组不同即拒绝发布，不通过随机尾号掩盖冲突。目录 ID 是排序后的 entries 与 policy/grant 版本的 canonical JSON SHA256。只保存不可变 tuple，调用方拿副本。

M2 无业务分发函数；暴露 lease 与 assert_current 为 M3 所需的约束接口。发现快照发布前重检当前状态、discover许可与generation。禁用/refresh 以 DB commit 为线性化点：commit 后获取的 lease 一律拒绝；此前已放行的initialize/list_tools可能已在执行，其发现结果在commit后不发布。此规则不给M2增加业务调用入口。活动进程内 token 注册取消事件，禁用发 DB NOTIFY 作尽力加速；跨进程取消通过最多100ms权威 head 轮询加速，**正确性依赖每次管理连接与快照发布前DB重检，不依赖 NOTIFY**。网络响应与 disable 并发时，发布检查取共享行锁并在短事务完成 receipt，disable 更新需等该事务结束；结果要么先发布、要么因新 generation 拒绝，有明确先后关系。

## 8. Schema 与业务合同门禁

首版采用 `mcp-business-profile-v1`，不声称接受任意 JSON Schema 或自动证明两个 Schema 等价。

- 服务 `list_tools` 中绑定工具必须存在且原名唯一，inputSchema/outputSchema 均为 object。M1 能力/版本固定八项；未知能力不启用，发现但未绑定工具只可供管理员查看脱敏名称。
- 期望 inputSchema 为 M1 CapabilityRequest 的结构 Schema，将 capability 属性固定为该 binding 的 const、contract_version 固定1；输出同理基于 DynamicEvidence。cross-field 语义依然在本地 Pydantic 执行，Schema 匹配不能取代 bind_evidence。
- 为保持可验证性，首版只接受与本地期望 Schema **规范化后精确相同**的业务 Schema。规范化只移除 title/description/examples/$comment，排序 object key；不移除 additionalProperties/required/format/约束，不接受远端新加可选 tenant/user 字段，不自动删约束迎合模型。
- 支持本地生成所用 type/properties/required/additionalProperties/$defs/本地 `$ref`/anyOf/enum/const/items/minItems/maxItems/minLength/maxLength/pattern/minimum/maximum/exclusiveMinimum/exclusiveMaximum/format 等固定关键字。未知关键字、远程 `$ref`、循环 ref、超深或过大拒绝；格式校验启用 date-time；不执行远端正则或引用抓取。规范匹配后仅运行本地已知 Schema 的 validator，避免远端 regex 注入造成计算风险。
- M2不直接import jsonschema、不新增依赖。生产只做本地规范Schema精确比较及发现合同校验；tests中的真实SDK使用其既有校验，业务实参/结果以M1 Pydantic为权威，真正业务执行边界留M3。
- 工具 annotations.readOnlyHint 可以记入诊断，不能改变 enabled 或授权。描述和返回正文不能请求宿主启动程序、扩大 readers、替换目标或索取凭据。

精确 Schema profile 的限制写入接入说明：已有 MCP 只有自由文本输出、没有 outputSchema、与约定结构不同，即使协议可连也不通过业务合同。后续扩大 profile 需独立测试与版本，不在本包顺带引入通用 Schema 转译器。

## 9. SDK 生命周期、失败和发现诊断

RuntimeManager 每次操作从可信 policy/credential 获取 resolved profile，创建 AsyncExitStack，按 transport → ClientSession 顺序进入，逆序退出；HTTP 自有 client 最外层进入/最后关闭，terminate_on_close=True。同一会话仅属 `(tenant,service,config_revision,generation,credential_generation)`，不跨租户复用。

固定本轮管理限制：连接+initialize 5秒，发现整体10秒（含分页，最多10页/50工具），管理操作总20秒；cleanup 有独立最多8秒屏蔽外部取消的清理窗口。超时预算用 monotonic clock，不由服务参数修改；无自动重试发现请求，断连后没有隐式重发。业务call不在M2生产接口内。

SDK 通道禁止 server-initiated sampling/elicitation/roots 文件读取，显式回调返回协议拒绝，日志回调只记类别/服务与调用号，不保存正文。实验 task handler 不对远端开放能力。ClientSession 初始化失败、list_tools 失败或分页未完成均退出会话。

跟踪outbound JSONRPC initialize/tools/list的真实wire request id（沿用旧 RequestTrackingStream 公共边界方式），按 task 记录；取消/超时/禁用时尽力发送 `CancelledNotification(requestId=真实id)`，随后关闭会话。捕获 Exception 做结构化错误，不吞 BaseException；调用方取消继续传播 CancelledError，清理与取消诊断只留下元数据。远端不配合取消仍拒绝迟到结果。

**生产调用边界：** runtime只有discover与close；CLI没有diagnose/call/request-file，服务端Schema或返回内容无法触发tools/call。SDK会话始终封装在发现函数内部，不返回ClientSession或可调用闭包。测试对生产runtime的wire记录断言只有initialize、notifications/initialized、tools/list、notifications/cancelled及传输关闭相关消息，绝无tools/call。

**测试专用协议调用：** `tests/test_dynamic_mcp_runtime.py`内直接用官方ClientSession连接本包固定合成fixture，调用固定假对象，验证structuredContent、真实request id取消与清理。测试helpers留tests内，不从src导入/导出通用call方法，不读取真实企业注册或业务凭据。该证据只证明SDK transport具备调用/取消机制，不能视为本地Registry/Policy/Executor业务集成；后者是M3必须单独交付的门禁。

错误code固定（含CLI映射）：in_progress、outcome_unknown、unsupported_target、access_denied、invalid_configuration、target_not_allowed、credential_unavailable、connect_timeout、initialize_failed、discovery_timeout、discovery_incomplete、schema_unsupported、contract_mismatch、cancelled、disconnected、oversized_result、source_conflict、version_conflict、idempotency_conflict、stale_generation、cleanup_failed、storage_unavailable。CLI不输出原始 exception/headers/URL凭据；远端错误文字不改写成事实。

没有跨 DB/外部服务的分布式事务。record_discovery/发现receipt 失败时返回 storage_unavailable、不发布目录、不伪称成功。网络已发生但结果未知时持久化operation状态为outcome_unknown、command receipt也明确记录outcome_unknown（若 DB 不可用则只向调用方返回该状态，不假装已持久化）；同command不能自动重发管理请求，管理员须以新command_id显式发现。注册/启用等纯 DB 命令依赖幂等恢复。

## 10. CLI 合同与本地操作

独立入口 `uv run --no-sync python -m anlan.interfaces.mcp_registry_cli`，不改 `anlan` 主 CLI。注册配置文件最大64KiB，UTF-8（含可选BOM），extra forbid，禁止 stdin 自动读取未知正文作为命令。

命令：`initialize`、`register --file ... --command-id ...`、`replace --tenant ... --service ... --expected-generation N --file ... --command-id ...`、`discover`、`enable --validation-digest ...`、`disable`、`refresh`、`inspect`、`list`、`reconcile`。所有修改命令必须 command-id；除首次 register 外必须 expected-generation。--tenant/service 是作用域选择器，不能改变认证 principal 的许可集合。发现只用受信profile，CLI无diagnose/call/--request-file/--url/--command/--shell参数。

stdout 每操作一行 JSON，仅 schema_version=mcp-admin-receipt-v1、command_id、tenant/service、状态、generation/config_revision/discovery id/validation digest、error_code、cleanup状态和耗时。敏感发现正文不输出；仅输出工具数量、协议版本、Schema校验状态等结构概要。stderr仅脱敏操作错误。exit code：0成功或幂等重复；in_progress映射4并附状态，outcome_unknown映射5，unsupported_target映射5；2输入错误；3拒绝授权；4版本/幂等冲突；5协议/合同/目标问题；6存储故障；7清理失败；取消映射130。不得因清理失败仍以0冒充完整生命周期成功。

## 11. TDD 实施顺序与实际验收设计

D通过后才建源码/SQL/测试。每步先编行为用例，运行并记录预期 RED，再最小实现/观察 GREEN；缺PG环境记录未验证，不改测试跳过、不将 skip 计通过。源码与 fixture 不含真实模型/云服务调用。

1. **管理授权与目录纯合同**：普通Identity/普通Bearer不能得到AdminPrincipal；无tenant/action拒绝且DB/网络/resolve调用数为0；reader缺记录空目录、跨租户同service不互见；别名确定且碰撞拒绝；可变原始输入不能改变冻结目录。先写 test_dynamic_mcp_catalog/cli 的失败用例，再实现对应纯边界。
2. **PG 注册版本**：显式独立测试DSN；initialize两次幂等、缺基础schema失败；两个连接同时expected_generation=N修改仅一个成功；另外两个不同service对同tenant/capability/factory并发enable，仅一个成功，另一个source_conflict且保持validated；绑定键排序锁避免write skew与死锁；同command同内容回原receipt、异内容冲突；跨tenant/actor隔离；事务注入失败无孤儿head；不可变revision/discovery/command UPDATE/DELETE被DB拒绝；禁用/refresh/replace单调递增且旧lease拒绝。先 registry RED，再建022和registry。
3. **真实 stdio SDK**：合成fixture通过当前Python绝对路径+固定`-m/脚本路径`运行，通过生产runtime执行真实ClientSession initialize/list_tools并断言无tools/call；另在tests内直接SDK连接固定fixture做合成call_tool协议测试；覆盖分页、缺outputSchema、不支持ref、未知/重复工具、oversize；server日志只向测试临时文件写事件/PID/实际request id，不写secret。timeout/cancel收到对应CancelledNotification，最后PID退出、管道结束；初始化中途失败也关闭。默认SDK标准stderr重定向到宿主有界脱敏sink，secret sentinel不进入stdout/stderr/trace/DB。
4. **真实 Streamable HTTP SDK**：本地127.0.0.1动态端口运行FastMCP/uvicorn合成服务器，使用真实socket和SDK transport，非MockTransport冒充；验证生产runtime的initialize/分页且wire无tools/call；tests内另测固定合成call；覆盖session delete、客户端关闭、断连、取消、同源和跨源3xx均拒绝、错误path/目标/tenant不发送Authorization、无代理继承。IP字面量HTTPS校验可用受信测试证书另验；无证书则明确未验证生产TLS。
5. **状态竞争与恢复**：网络返回前另一DB连接disable/refresh/replace；旧结果不写validated、不发布目录；跨进程轮询取消时限；DB在发布前失联返回storage_unavailable；停止后不复活旧head。CLI/API对diagnose/call及request-file输入明确拒绝，生产wire无tools/call；生产runtime不返回可调用会话句柄。
6. **CLI 集成与旧回归**：子进程实际调用独立模块，admin token只在环境，验证exit/JSON/无泄漏/普通Bearer拒绝。运行下列命令并保存真实passed/skipped/errors/warnings与时间；独立代码审查修复所有critical/important后再由主窗口装配。

```powershell
uv run --no-sync pytest -q tests/test_dynamic_mcp_catalog.py tests/test_dynamic_mcp_cli.py
uv run --no-sync pytest -q tests/test_dynamic_mcp_registry.py
uv run --no-sync pytest -q tests/test_dynamic_mcp_runtime.py
uv run --no-sync pytest -q tests/test_dynamic_mcp_contracts.py tests/test_tool_registry.py tests/test_tool_executor.py tests/test_tools.py tests/test_tool_loop.py tests/test_tool_model.py tests/test_knowledge_tool_loop.py tests/test_business_bridge.py
uv run --no-sync ruff check src tests scripts evals
git diff --check
```

PG用例需显式 `ANLAN_TEST_DATABASE_URL` 指向隔离合成开发库，使用唯一synthetic tenant/service标识，不truncate共享业务表/不修改主库初始化；多进程SDK测试与PG竞争测试都要真实执行，不以fake断言替代。缺环境列未验证并阻止对应退出门禁，不能无限宣称工程通过。

验收矩阵：

| 要求 | 必须保留证据 |
|---|---|
| 普通身份不能管理 | 业务Identity/普通Bearer负例，零DB/网络/resolve |
| 注册/发现/验证/启用分离 | 每状态及失败的PG head/discovery/receipt，无自动启用 |
| 版本/并发/幂等 | 两真实连接竞争、重叠服务同时enable、重复网络命令只占位一次、失联恢复 |
| 受控目标与凭据隔离 | argv替换拒绝、未许可URL/redirect无外发、secret sentinel全出口不见 |
| 官方SDK实际生命周期 | stdio真实PID、HTTP真实socket、生产initialize/list/cancel/close；call仅tests固定合成fixture |
| 统一执行器不绕过 | src无diagnose/call导出，CLI拒绝调用命令，生产wire无tools/call；M3才接Registry/Policy/Executor |
| Schema变化不扩权 | refresh先撤旧目录、坏schema不启用、未绑定工具不发布 |
| 禁用与迟到结果 | commit后新lease拒绝，运行中取消，旧响应拒绝发布 |
| 目录隔离 | tenant/user/capability/factory四重过滤及冻结版本 |
| 旧链兼容 | 固定tools/model/knowledge/business_bridge定向与Ruff真实结果 |

## 12. 失败恢复、回滚与退出

进程在网络操作中崩溃：会话属于操作进程，重启不重用；head若refresh已置registered则保持停用。注册/enable提交后CLI未收到结果，用原command-id查receipt恢复，不重放外部管理请求。未完成discover先将原operation确认为outcome_unknown，再由新command重新执行；不完整列表不能作为有效快照。

禁用失败若DB不可用：禁止新发现/目录加载（fail closed），不能声称全局禁用已提交；报告storage_unavailable。远端会话取消失败报告cleanup状态，保留generation撤权；DB成功禁用不会因cleanup失败回退enabled。

回滚仅撤本包新CLI/三个模块/fixture/测试及未应用022；若022已应用，先将相关服务禁用、停止进程、撤宿主引用，再回滚源码。默认保留不可变注册/审计表，**不自动DROP或降head generation**；后续重装仍需重新发现/验证/启用。需要销毁测试数据库由主窗口按隔离环境流程处理。旧SQL不改、主初始化不动、原脏文件和其他窗口编辑不回退。

M2完成退出：管理与SDK定向实际通过、PG和真实两传输证据具备、无未解决critical/important、准确报告限制并交由主窗口集成；未验证TLS/企业服务如实单列。仍不等于M3动态业务查询、模型选源质量或企业上线。D审查通过之前，本窗口不创建本设计列出的生产代码、SQL或测试。

## 13. 自审结果

- 已将状态/配置标签/宿主并发号分开；明确网络锁外运行、返回后版本二检、禁用线性化与跨进程取消边界。
- 已移除生产diagnose/API/CLI，明确真实call仅tests合成协议验证与M3统一执行器分界、普通Bearer无管理授权、源竞争首版拒绝而非静默选源。
- 已核对实际SDK的自有HTTP client关闭、HTTP重定向和stdio解析前内存限制，未把接口替身称作真实SDK验收。
- 仅新增本设计文档；无编码、SQL变更、stage/commit、真实模型、部署或云操作。待D审查。


## 14. D初审修订记录（仅设计）

1. enable对跨service重叠来源的检查与写入采用排序后的(tenant,capability,factory)事务advisory locks；明确两个不同service同时enable仅一个成功、另一个source_conflict的真实PG回归。单独head行锁不足以防write skew。
2. 删除M2生产diagnose方法、管理action、CLI命令、请求文件输入和业务调用返回合同。生产runtime仅初始化/发现/取消/关闭，不返回ClientSession。call_tool仅在tests直接连接固定合成服务时验证SDK transport，绝不提升为管理员绕过Registry/Policy/Executor的入口。
3. 最终D已批准：以上修订写回后可直接按TDD实施。确认022归本窗口、显式registry.initialize、不改旧主initializer；discovery仅持久化规范Schema与宿主诊断，不保留远端description；补齐in_progress/outcome_unknown/unsupported_target映射；不直接import jsonschema。


## 15. 实施接口冻结与环境

- catalog共享冻结接口采用frozen Pydantic和tuple：`DiscoveredTool(name,input_schema_json,output_schema_json)`（schema只存规范JSON字符串）；`DiscoverySnapshot(discovery_id,captured_generation,protocol_version,server_name,server_version,discovered_at,tools,digest)`；`ValidationReport(valid,tools,error_codes,digest,schema_profile)`。辅助函数为`sanitize_tool`、`make_discovery`、`expected_schemas`、`canonical_schema`，无需jsonschema新依赖。
- 2026-11-16本窗口已创建独立`anlan_mcp_20261116`，显式启用vector extension并执行基础initialize_database成功；未drop数据库。Windows psycopg异步使用SelectorEventLoop；SDK1.30自带Windows进程fallback与Job Object，需真实测试确认组合，不自行修改SDK。
- 初次环境初始化因默认ProactorEventLoop被psycopg拒绝，改用明确SelectorEventLoop后成功；没有修改产品代码或测试来绕过环境问题。凭据/DSN未输出。
