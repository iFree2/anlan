# 取消项目调用次数上限：交付验证

2026-10-25。用户在查明当前累计100/100导致确认分类失败后，明确要求“不要有额度限制”。这是对原100累计/30对话/10材料事件约束的后续覆盖授权；不允许重置历史、不自动授权代理付费联调或无限自动重试。设计/计划f3b9432，实现与管理helper98ce6b3。

## RED/GREEN与工程检查

新增tests/test_audit_only_budget.py在真实本地PG隔离库先3失败：策略表/limits_enforced缺失，非缺环境。SQL018增加model_call_policies（无行默认限额），初始化不覆盖管理策略；reserve读取策略时持有原AUTH行锁，仅显式false时跳过两个次数比较，仍reserve/finish/失败记账；DB不可用仍拒绝。原授权和分包上限数值不改。

新测试与test_budget、test_release_budget、test_console_live（模拟HTTP供应商、非付费）、test_conversation_model、test_package_layout实际 **75 passed，0 failures/errors/skipped，30.29s**。包括耗尽后关闭可继续并发12条独立审计、原失败逐字段保留、重连/initialize不重置、默认限额保持、客户端不能开放策略、audit_only/null有效额度展示。部署故障测试test_audit_only_rollout.py先因新helper不存在而RED，实际提取activate，注入停服后首次snapshot故障，验证转维护而非DB恢复；GREEN1 passed。

新wheel离源码导入/18资源/9CLI通过；实际4服务进程恢复单项1 passed/91 deselected，37.32s。全目录Ruff、diff通过。原905项是此前制品验收，未称本次新源码完整全仓重跑。应用侧与运维两次独立只读审查均无Critical/Important/Minor；审查者没有运行/SSH/模型调用。

## 云端实际检查

固定host key SSH，凭据只在原私密桥接内读取。先核对旧p12-demo-tokens、无pending和100/29/7真实计数；备份DB与配置到 `/opt/anlan2/shared/before-p12-audit-only-20261025/`（root0700/敏感0600），DB自定义dump通过列表验证，SHA `bb3ccf792f06b64d3d1e46b2b3ab7c39ba9004ee33be24a4dbb277c0bb0958ec`。

新发布 `/opt/anlan2/releases/p12-audit-only-20261025`，wheel SHA `398635367cf5aed1a91153023a324f1b8b296c77124dbc2483abf832a5a0d572`；管理helper `/opt/anlan2/release-audit-only-20261025.py` 源码SHA `15f49384144e6af528cfec780c6c08a174f691d7d2c730a0b48c0d0829056e7a`。prepare校验制品/新配置，复用既有依赖；activate停服务后再次无pending，SQL018和AUTH行锁后的唯一false策略在同一事务提交，才切换/启动。没有增加新工作包、删除/退还调用或改原限额行。

实际服务PID3440482、nonroot anlan2。激活与另一次只读复查确认126文件逐字节匹配wheel，schema18已登记/12未启用，旧业务/100尝试和根站点完整保留，原角色令牌不变。三身份info均audit_only，limits_enforced=false，有效总/包/剩余null；当前计数总100、对话29、材料事件7，pending均0。原用户申请仍draft/version1、等待确认，不代用户操作。[终检](evidence/audit-only/final.json)。

公网浏览器导入现有申请人配置，实际显示“项目调用次数不限（保留记录）”，输入清空、local/session storage为空。只做GET/加载已有会话，没有发送消息或调用供应商；本次付费模型请求0，没有用真实101次证明限制关闭。限制关闭的动态行为由真实本地PG审计测试证明，线上证据是实际策略/安装制品/公开info。

恢复只用本新helper rollback（维护503）/forward（同一新版）；不恢复数据库或切旧写应用。停服后异常已在try保护内，失败维护，保留DB政策和审计。此次没有额外实切维护/重录视频，不冒用B5旧实录作本次新恢复实验。

## 仍然保留的边界

没有取消DeepSeek余额/限流、请求大小、单次超时/循环、角色/版本确认与审计保护。取消次数限制不能保证模型输出格式正确或网络永远成功，旧失败提示保留为历史。公网HTTP和弱口令意味着他人猜中后可能消费模型费用；建议仅短期合成演示。自动化p12仍已删除，不因取消项目限额而恢复后续开发或自动付费工作。
