# P8-WP01验收

- [x] 同源页面可在浏览器启动；材料缺项、追问、补充/修订、版本和当前状态可见。
- [x] 两类合成事件绑定当前任务；列表来自PG，重复提交不重复入库。
- [x] 真实本地工具/知识与明确替身核查可见；未知依据和失败不隐藏。
- [x] 人工反馈持久化；材料修改后旧核查过时，旧反馈拒绝且原报警不变。
- [x] 刷新重连恢复记录；无身份/跨身份/额外身份字段均被服务端拒绝。
- [x] Token不保存到浏览器持久存储/URL/日志；静态资源包含于wheel。
- [x] 实际浏览器路径、必要测试与证据保存；零新增模型请求。
- [ ] 本人理解/修改/排错证据独立待验证。

证据：[WP01验证](evidence/verification.md)、[CI-v3](evidence/ci-final-v3.json)、browser-final/report.json。

## WP02用户追加部署验收（已验证）

- [x] 独立目录/数据库/非root服务部署，不覆盖已有业务。
- [x] 公网/anlan/操作台完整路径与真实PG/向量知识查询运行。
- [x] 服务进程重启后任务、事件及反馈恢复，旧反馈拒绝。
- [x] 46次历史模型账本保留，不重置计数；零新真实模型请求。
- [x] 访问/运维/回滚说明与无凭据报告交付；实际限制保留。

证据：cloud-browser-v1/report.json、restart-result.json、cloud-http.json、budget-cutover.json；访问/限制见[部署说明](deployment.md)。

最终只读交接核对见[final-readonly-verification.json](evidence/final-readonly-verification.json)。预算迁移的公开报告为汇总与本地冻结证据，不含云端逐条字段比对；不得据此扩大为重复导入安全或逐条一致性已独立验证。
