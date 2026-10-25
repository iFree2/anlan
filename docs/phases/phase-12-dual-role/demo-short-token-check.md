# 合成演示短令牌验证

2026-10-25。用户指定两个不同角色口令，并在知晓原32位限制/弱口令风险后明确批准仅演示启用的最小改造；具体值不入库。批准设计/计划提交7b8b2a3，实现a8f8ab3，运维异常修复9484278。本次没有新批次、自动化、模型请求、SSO或正式审批范围。

## 验证记录

- RED：新增配置/网页测试3 failed、8 passed、1 PG排除，因无显式标记和网页语法功能失败。GREEN：11 passed/1 PG排除。普通TokenGrant缺省仍拒绝短值；演示marker严格布尔，ServiceConfig强制synthetic-、协作角色和固定as_of。
- 真实loopback PG17隔离库 `anlan_demo_short_20261025`：新增及collaboration_config、console、collaboration_console、service_api、collaboration_api、package_layout相邻回归52 passed、0 skipped，55.00s。未连接云端PG执行测试，未运行live pytest。
- 新wheel实际4进程恢复：test_collaboration_release.py中wheel_process_restarts单项1 passed、91 deselected，38.82s；包检查离源码导入/17资源/9CLI成功。应用wheel SHA `b2e62fcb568d4cca61767eba8c78893de3bce91749f2969683d09b2cfcce8b5f`；服务125文件与其逐字节相同。此前905项不充当本次新源全仓测试。
- 只读审查指出activate停服务后首次snapshot在try外，失败会留下停服；用实际activate函数AST提取+管理stub确定性注入故障。初始Windows无symlink权限是fixture环境问题，改用普通目录后实际RED为未进入恢复分支；修复后配置单元与恢复测试12 passed/1 PG排除。恢复检查覆盖四配置、原P12路径、start及ready。复核无Critical/Important/Minor。源码保留在deploy，非secret。
- 全目录 `ruff check src tests evals scripts deploy` 通过，diff检查通过。结果不相加冒充新的全仓数量。

## 实际部署与访问

沿原固定主机指纹SSH桥接，配置只在进程/私密目录处理。先备份四份配置和原P12路径到root0700/配置0600目录 `/opt/anlan2/shared/before-p12-demo-tokens-20261025/`。新目录 `p12-demo-tokens-20261025` 复用既有依赖，未升级系统组件、未改SQL/DB或根站点；验证新配置后才短时停旧服务、原子切换/重启。服务active、User=anlan2、PID3434158。

激活检查所有业务行和账本完全不变、新两令牌200/旧两令牌401，原legacy令牌及所有身份保持；匿名401。后续只读复查确认两角色看到原同一申请review_completed/version5，互读私聊404，原站点摘要未变、无pending。最终账本91/100、对话21/30、材料事件6/10，新增模型请求0。[云端终检](evidence/demo-short-token/final.json)。

公网浏览器实际使用两独立上下文：申请人手输新值点击连接，安全人员导入新配置，均正常加载本人原会话/同申请，弱安全提示可见；输入字段成功后清空、local/session storage为空。未发消息、未新建申请或消费额度。两本机 `.runtime/p12-b5-access/` 配置已下载替换且私下逐值核对匹配用户要求，旧副本在 `before-short-token-20261025/`。只关闭本次两个浏览器页。

恢复使用 `/opt/anlan2/release-short-token-20261025.py rollback|forward`；维护应用不接DB/业务API，forward指向支持新配置的新版本。原P12 helper的forward不兼容新标记，已在当前部署说明更正。此次没有重复维护实切；保留B5先前真实维护503证据与本次新恢复代码回归，不混称同一验证。

令牌只是弱安全演示bearer，不是独立密码系统；不改变公网HTTP和无SSO的限制。未来上真实环境应恢复强令牌及适当认证传输措施。未重录视频，旧业务视频仍有效。
