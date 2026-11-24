# SYNTHETIC 人员三能力首包

全部为合成示例，不代表企业事实或正式进场授权。参考服务为 tests/fixtures/dynamic_mcp_personnel_server.py；使用受信本机 Python 固定绝对路径和精确 argv，不接受聊天提供的命令或目标。真实SDK端到端测试入口为 tests/test_dynamic_mcp_personnel_e2e.py。

宿主注册服务时将 contractor.qualification.query / person.training.query / person.access.query 分别绑定到对应工具名，factory_ids=[F001]，contract_version=1。使用既有独立管理员 register → discover → inspect → enable 流程；普通业务身份不管理服务，主initializer不自动启用。

PersonnelPolicy 需由可信宿主提供：tenant_id、policy_version、directory_version、厂区别名、contractors、persons、users。Contractor记录name与factory_ids；Person另含contractor_id。grant分别含factory_ids、contractor_ids、person_ids、qualification_categories、training_categories、capabilities。目录版本覆盖本包厂区/对象关系和名称，不能从模型或远端正文补造。

示例对象：contractor-1=合成承包商，person-1=张三，属于contractor-1与F001。资质类别hot-work，培训类别safety。两类授权不能互换；同名目录条目必须提供显式ID。具体构造代码见端到端测试中的PersonnelPolicy/PersonnelRequest。

入口：`anlan.workflows.external_inquiry_personnel.check_external_personnel`。参数与设备首链相同（service, identity, request, policy, registry, host, model, trace, limits），request采用PersonnelRequest；model可复用已有ScriptedDynamicToolModel。该模型仅协议替身，零真实模型请求。可信host.authorize(snapshot)必须按当前策略版本/目录版本/对象关系重检，生产身份不由示例lambda提供。

正常合成记录故意包含 active资质、completed培训、denied准入，验证三类证据不会推导为允许进场。报告status=awaiting_review、summary_status=unverified_candidate；completed只表示必查观察齐全。unknown/partial_empty保持缺证；wrong_category/wrong_object被M1绑定拒绝并记录失败审计。首包只请求第一页，不自动翻页或换源。

继续沿同一本地Registry/Policy/Executor/SDK/SQL023审计；无普通对话或操作台装配，无审批、发证、授权写入或设备/报警控制。作业票、历史双源与生产TLS/企业系统另待验证。
