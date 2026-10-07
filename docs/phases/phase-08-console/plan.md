# P8-WP01：轻量本地操作台

2026-10-07用户明确增加材料表单、补充追问、事件列表、核查结果和人工反馈，用于熟悉项目。长期授权覆盖常规设计与实现。P1—P7历史交付保留；本包不创建新任务/自动化，不修改旧项目，不发送真实模型请求。

## 设计

采用FastAPI同源静态HTML/CSS/ES模块，复用原材料/事件/感知运行时。相比独立React/Vue工程，减少构建和启动步骤；相比只做CLI包装，同源页面可以直观看到追问、版本与事件。新增interfaces/console包（路由/服务/页面资产）；不把前端逻辑塞入原api.py。

材料调用原/tasks及resume/revise；新增有界、tenant/user过滤的任务/事件/核查历史查询。console_profiles是显式服务端测试授权配置：为可信身份绑定一组人员/区域只读引用。合成事件仅选择两类，身份、区域、task/revision/run、时间与序列由服务端确定。接收与原始报警提交完成后才允许显式核查；反馈仍调用原服务端revision/currentness控制，不生成审批决定。

操作台核查固定scripted_double，材料offline；页面显示合成数据与模式。Token通过用户选择ignored本地配置或手动输入，只有页面内存，不写URL/localStorage/sessionStorage/日志。DOM使用textContent；静态CSP禁止外链脚本、内联脚本与任意远程连接。列表只查询当前身份，最新50条，不全表导出。刷新后重新连接并从PG读取，不由浏览器保存业务状态。

事件模拟复用EventStore原接收规则，仅增加复用调用者事务连接；任务锁与来源锁按既有顺序。同request_id返回同一原事件，内容冲突拒绝，不更换时间/序列制造重复事件。不同任务拥有不同演示来源，不使无关任务事件过期。模型、实时阈值/联锁、告警关闭、完整门户不属于本工作包。

## 实施（writing-plans/TDD）

- [x] 冷启动smoke，保护用户未提交区；先新增tests/test_console.py，静态壳/认证/两事件/幂等/跨身份/修订后过时及反馈拒绝应失败。
- [x] ServiceConfig增加可选console_profiles（缺省关闭模拟）；新增interfaces/console/service.py及routes.py，安装同源页面与/console/api路由。原接口不改变。
- [x] EventStore接收支持调用者连接；模拟在锁内取当前checkpoint、生成固定事件数据并复用原接收，提交后显式review。验证同请求不重复、旧expected_revision拒绝。
- [x] index.html/styles.css/app.js/api.js：连接、材料/追问与修订、任务列表、两类事件按钮/事件列表、证据/未知/结果/反馈、错误状态与原始JSON折叠；禁止自动网络重试与模型调用。
- [x] scripts/prepare_console_demo.py生成新的ignored配置并摄取现有示例知识，不覆盖已有凭据。输出只含路径/模式，不打印token；配置文件在浏览器本地选择，页面仅保留必要token。
- [x] 真实PG定向pytest：`.venv/Scripts/python.exe -m pytest tests/test_console.py tests/test_service_api.py tests/test_events_postgres.py -q`。运行浏览器材料缺项→补充→两事件核查→反馈→修订→旧反馈拒绝→刷新恢复；保留截图/安全报告。
- [x] 本次源码wheel包含静态资源并验证安装资源；只在源码稳定后运行必要全量CI。更新README、architecture、roadmap/status/matrix/learning与本阶段acceptance/handoff。个人掌握待验证，用户原译文及.idea/learning整文件不stage。

## 自审

五项页面对应同一条现有业务链。页面创建演示事件不是实际设备接入；列表状态不代替实时currentness，选择核查记录时再读原get。只有服务端可信profile决定事实对象。旧来源/API继续可用。未知/失败必须可见，前端不能把Schema有效或替身完成称为真实模型质量。

执行状态已按验收与现有运行证据核对完成；最终只读复核见[evidence/final-readonly-verification.json](evidence/final-readonly-verification.json)。本人掌握仍待验证，预算逐条比对证据边界见[交接](handoff.md)。
