# P8-WP03：线上真实 DeepSeek 接入

2026-10-07用户明确要求线上使用DeepSeek；后续多模态意愿不扩大本包范围。现有长期授权覆盖实施与发布，缺少SSH连接时只暂停云端步骤。

目标：材料与事件核查使用既有deepseek-flash适配器，页面显示实际模式、语义失败与预算；仍为合成学习数据，AI不能批准作业或改变报警。

方案：服务端ServiceConfig显式选择deepseek_live，密钥来自进程环境；生命周期管理一个HTTP客户端，每个动作构造有界模型实例，复用同一云端BudgetLedger。新材料持久化deepseek_live模式；旧offline材料不能续写或新增事件/核查，避免把旧分析冒充真实模型结果；旧核查仍允许按原版本/currentness规则记录人工反馈。事件查询继续读原PG。P8-WP03是本包唯一预算名，材料/事件共用10次，累计100不变；SQL010只扩展允许的包名，不复制、重置或返还账本。

选择理由：仅接事件不能满足完整操作台真实AI要求；另建推理服务会重复已有适配器及预算控制。因此采用两链路原位接线，既有CLI默认P5预算行为保持不变。

## 执行计划（writing-plans / TDD）

- [x] tests/test_console_live.py先验证真实PG＋HTTP替身传输的两链路、预占先于HTTP、同请求幂等、跨身份拒绝、旧offline任务只读、失败不退回替身、预算耗尽无HTTP、缺密钥启动失败；保存red证据。
- [x] 新增interfaces/service_models.py负责模型与客户端生命周期；修改api.py/console routes与service按服务端模式接线；修改llm/perception.py与workflows/perception.py支持明确的P8-WP03常量，默认旧包不变。
- [x] BudgetLedger初始化执行SQL010；仅增加P8-WP03合法值，测试原限额、历史记录和冻结规则不变。页面从info及每条结果读取真实模式，显示语义状态与调用余量，旧离线任务提示新建。
- [x] 运行定向PG合同测试、ruff与源码稳定后的本地CI；独立审查本次diff。测试使用独立authorization和HTTP替身，不在冻结本地生产账本预占。
- [x] SSH可用后只读核对当前发布、配置和云端账本；记录历史规范化摘要。制作独立新发布目录与回滚指针，私密环境中配置既有DeepSeek密钥，保持原网站/PG/库/身份/任务。
- [x] 原子切换发布并重启本应用；用至多3次真实请求验证材料及两类事件，明确保留所有失败/预占，余额供用户后续使用。本包最多10次，不隐式重试，不换包绕限。
- [x] 验证原网站、旧记录、模型模式、HTTP结果与云端预算增量，更新status/deployment/handoff与证据，选择性提交；用户16路径译文、learning-log、.idea及私密文件不提交。

验收命令：配置本地测试PG环境后运行`.venv/Scripts/python.exe -m pytest tests/test_console_live.py tests/test_console.py tests/test_budget.py tests/test_perception.py tests/test_perception_postgres.py tests/test_service_api.py -q`，预期全通过、零跳过。云端验收必须看到材料analysis.model/semantic_status与核查report.mode/attempt_id/usage，不把HTTP200或标签当真实模型成功。

访问约束：沿用HTTP/IP学习入口，密钥绝不进入浏览器/报告/Git；未配置TLS和生产认证。缺管理连接时不能声称线上已切换；未验证真实图像/视频、生产效果或本人掌握。

恢复边界：成功响应的同request_id重放不新增请求；模型响应后checkpoint落盘前中断时，显式recover可能再次调用并计入同一预算。页面按钮已提示，不承诺故障窗口恰好一次。

最终执行：新发布已启用，实际3次DeepSeek调用均成功、6342token，累计49/100、包剩7；云端证据见live-cloud-acceptance.json与live-cloud-budget-after.json，原46条逐字段规范化一致。
