# P8交接：轻量操作台与用户授权云端学习部署

用户10月7日追加的五项操作台与阿里云部署已完成运行验收。原P1—P7历史包不重做；原自动化2-0已删除，不新建循环或P9。个人掌握仍待本人证据。

## 当前入口

[部署/访问说明](deployment.md)，公网http://47.93.218.52/anlan/console。本机ignored访问文件.runtime/aliyun-console-access.json供浏览器本地选择，不打印/上传配置正文，不含SSH/PG管理密码。云端模型为替身，材料offline，原报警无控制入口。服务器新数据库anlan2_console和systemd用户anlan2；原PG13/现有库/网站保留。

## 实际成果与证据

WP01：同源HTML/CSS/ES模块、材料补充/修订、PG任务/事件/核查列表、两类服务端合成事件、受控候选/未知/引用和人工反馈。身份/事实引用来自可信console_profiles；事件task/revision/run/序列来自服务端。request_id跨kind冲突拒绝；selected taskId独立于snapshot；选择/提交/刷新/恢复失败先清旧核查。SQL009 bigserial排序与固定业务时间分开。

本地CI463 passed/0skip：[ci-final-v3](evidence/ci-final-v3.json)，v2通过记录亦保留。browser-final九项通过，7个console包文件与wheel源码一致、SQL009在包中。初始red/幂等red、移动端溢出、缺浏览器、一次环境中断未完成CI均保留；不能把重跑通过反推环境中断根因。

WP02：独立Python3.13.3/uv0.7.5、锁定hash依赖、当前wheel、固定BGE缓存、官方pgvector0.8.6在原PG13安装，systemd非root8018、Nginx/anlan/。公网浏览器九项及三工具/知识ok；服务PID变更后PG任务/事件/反馈/结果快照完全相同。首次重启读取未成功而后就绪复验，失败保留；原网站摘要不变。

模型预算：[ADR014](../../decisions/014-console-cloud-deployment.md)。原46次尝试迁移云端唯一生产账本，100/10上限不变；本地同authorization已触发器冻结，读历史/其他测试授权不受影响。部署模型请求0，不迁移docs/DS.txt或模型密钥。恢复本地live前必须先单一账本交接，不能两份独立花费。

独立交接复核：[只读核验](evidence/final-readonly-verification.json)确认公网页面、健康/认证就绪、三份静态资源与源码一致，已有任务/两事件/反馈快照与restart-after一致，上手任务仍待补充；CI-v3受检源码与当前工作树一致，16条用户路径与保护基线一致。此次未登录SSH、重启服务、改数据库或重跑完整CI。首次误把未认证readyz预期为200的检查失败另存[记录](evidence/final-readonly-first.json)，认证后200，无应用修复。

预算证据边界：导入脚本逐字段写入首次新库，现有报告记录46次汇总及本地冻结；公开证据尚无云端逐条字段或规范化摘要比对。本次只读HTTP复核不补称已独立验证该比对。bootstrap遇已有attempt_id会忽略冲突，不应把重复运行当作账本修复或一致性验证。

## 关键文件

interfaces/console/{routes.py,service.py,assets/}；原interfaces/api.py/install_console与ServiceConfig/console_profiles；infrastructure/events.py支持调用者事务连接；sql/009_console_order.sql。scripts/prepare_console_demo.py、smoke_console.cjs、verify_console_deployment.py；deploy/aliyun/bootstrap.py、nginx-console.conf、freeze_local_budget.py。

云端/opt/anlan2/current与shared配置私密；只传wheel、必要合成资料、固定模型和预算历史，不上传旧项目、全仓库或开发凭据。发布包含保留的用户注释工作树，功能提交不包括用户16路径译文/.idea/learning-log整体。Git提交以本文件最新历史为准。

## 剩余事项与下一步

本人从页面亲自完成一个补充/修订/反馈场景，再按[学习五题](wp01-learning.md)找源码；未完成不标掌握。Q-P6-001 Judge误判、Q-P6-002同任务并发409仍开放；记忆/多职责没有已证实收益；云端HTTP/IP/模拟身份，未验证TLS/生产、Docker、真实设备或真实LLM页面效果。

后续如用户要求真实模型操作台、自动事件消费或生产认证，应另定具体小增量，不把本次脚本/页面效果当成真实模型质量。若继续，先读status/本交接/ADR014，核对Git和云端唯一预算；本地真实调用已冻结。原用户修改与学习目录保护要求继续有效。
