# P8-WP01已验证与保留的失败

2026-10-07。初始原服务smoke4 passed。新增console合同初次red4失败，随后真实PG27定向通过；审查发现同request_id换kind重复写入，红2失败，修复并增加首checkpoint前中断/固定clock排序后29相关检查通过。最终console7项通过。集合重叠，不把这些数量相加。

最终本地CI：ci-final-v3.json，463 passed、0失败、0跳过，锁/ruff/源码前后指纹通过；v2的通过记录保留。ci-final.json保留为未通过：验证进程和本地PG连接中断，测试日志不完整，无完整XML；原因尚未确认，不视为已通过或证明具体根因。恢复项目PG17后重新执行。

browser-v1：Playwright自带浏览器未安装，未进入页面。browser-v2：主链五项已通过，但移动端长引用使页面横向溢出；原件保留。换用已有Edge、修正引用换行后browser-v3通过。审查后的browser-v4/browser-final九项通过：追问补充、两事件/反馈、选择历史失败清空旧状态、GET无快照保留taskId恢复、旧反馈409、recover后重读currentness、刷新重连、DOM安全文本/令牌仅内存、390px无横向溢出。page_errors为空。

真实工具/示例知识的本地查询不是硬编码企业接入；材料offline、核查scripted_double、原报警active且独立。真实模型预算读取为46/100，本包不读模型密钥、不发模型请求。预算迁移与云端说明见[最终交接](../handoff.md)及budget-cutover.json。

独立只读审查报告五项P2，已增加/修正共同请求去重、选择原子更新、独立selected taskId、状态变更前清旧核查、PG递增入库顺序。初始服务/事件回归均实际执行。生产鉴权、告警控制与用户本人掌握未验证。

最终独立只读交接复核：final-readonly-verification.json，页面200、healthz200、readyz未认证401/认证200；原网站摘要、已有任务/两事件/反馈快照及三份静态资源均匹配。CI-v3 JSON与XML一致，当前受检源码无变更；未重跑完整CI、浏览器写入链路或SSH操作。首次临时检查错误地要求未认证readyz返回200，触发断言；final-readonly-first.json保留该失败，核对Actor认证依赖后更正检查，应用未改。

最终代码只读审查未发现阻塞有限学习交付的缺陷。非阻塞限制：bootstrap对已有attempt_id采用冲突忽略，公开预算报告缺少云端逐条字段比对；当前交接不补称该比对已验证。HTTP/TLS与生产认证限制继续保留。
