# P8交接：操作台、云端部署与真实DeepSeek

用户10月7日追加的P8-WP01页面、WP02云端部署及WP03真实DeepSeek接入均完成有限运行验收。原P1—P7不重做，不新建循环或P9，个人掌握仍待本人证据。

## 当前入口与使用

[操作台](http://47.93.218.52/anlan/console)。刷新后选择本机ignored `.runtime/aliyun-console-access.json`。点击“新建任务”，创建/补充/修订材料与新事件核查会使用真实deepseek-flash；失败计次，手动恢复也可能再次计次。可以只读查看“DeepSeek云端验收试件A接缝”的现有结果。旧offline材料不能续写或新增事件/核查，既有结果仍可按版本/当前性记录人工反馈。

材料语义和事件归纳为真实API；事实/知识/人员/区域/事件仍是合成示例，业务时点固定2026-09-22，不代替当前现场事实。无审批/报警控制和图片/视频上传入口。访问/回滚详情见[deployment](deployment.md)。

## 实际成果与证据

WP01实现同源页面、材料版本、可信console_profiles、两类服务端合成事件、候选/未知/引用与人工反馈；身份和task/revision/run/序列由服务端确定，request_id跨kind冲突拒绝，状态变更前清旧核查，SQL009按入库顺序排序。

WP02保留原Linux/PG13/现有库/原站点，独立数据库anlan2_console、systemd非root8018、Nginx/anlan/。初始offline/scripted浏览器九项与服务重启前后PG快照一致记录作为历史保留。

WP03的ServiceModels把材料和事件两链路接到真实DeepSeek，P8-WP03共用云端预算、失败不回退替身；SQL010只扩展包名。应用[CI467项](evidence/live-ci.json)通过、0跳过，当前源码与指纹一致；[wheel](evidence/live-wheel-v2.json)98源码/资源匹配。部署脚本[Linux故障模拟9项](evidence/live-rollout-safety-v2.json)验证临时文件异常清理、配置漂移拒绝、停止失败仍尽力回滚及旧就绪确认；实际切换一次成功，未做真实故障回滚演练。

公网浏览器实际完成材料1次、未戴安全帽/气体异常各1次真实调用：[验收](evidence/live-cloud-acceptance.json)。三次均成功，共6342token；材料semantic_status=checked，核查报告deepseek_live、attempt_id和usage存在、响应校验通过、三查询ok、两条反馈保存。刷新需重新连接，重连后结果/反馈仍在PG。截图在本次聊天中展示。[浏览器记录](evidence/live-cloud-browser.json)。

发布目录/opt/anlan2/releases/p8-deepseek-20261007，current已切换；旧发布venv作为依赖环境保留。PID2143209→2153128，app.env/console.json仍0600，密钥仅服务端。原网站摘要与旧任务快照不变。未重置DB、重装依赖或重载Nginx。

## 预算与限制

[云端账本](evidence/live-cloud-budget-after.json)：49/100，47成功/2历史失败/0pending；P8-WP03三次成功，包剩7次，累计100/每包10不变。原46条已与首次迁移文件逐字段规范化比对，发布前后相同，补齐先前仅有汇总证据的限制。本地生产authorization仍冻结，云端唯一写入，不退还失败或回滚次数；P1历史3次另列。

HTTP/IP/模拟身份仍未升级生产认证/TLS/SLA；未接真实设备、图片/视频输入或生产资料。历史Judge误判、并发409、引用缺口与未知故障保留。真实3次只证明本次接线，不证明全面模型质量或本人掌握。

保留WP01/02失败与WP03 red测试、旧打包脚本固定8SQL而实际10SQL的失败；先前SSH认证失败后改用用户明确提供的凭据非交互连接成功，不把失败一概认定为用户密码错误。重连时一次点击在按钮禁用期间超时，随后核对状态恢复，不增加模型请求。

## 后续

本包已交付，后续由本人按[学习五题](wp01-learning.md)亲自解释与操作，或提出明确小增量。管理凭据、访问文件、原16路径译文/.idea/learning-log整体不得提交；旧项目只读。后续启动先读status、本交接、ADR014，核对Git和云端唯一预算，不重复部署或付费实验。
