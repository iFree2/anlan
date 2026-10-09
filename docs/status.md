# 当前状态（唯一入口）

- 项目：安澜2.0。P1—P7原有限工程Gate已交接；用户10月7日追加P8操作台、云端部署及真实DeepSeek接入，WP01—WP03均已完成有限运行验收。工程完成不等于生产能力、模型泛化或本人掌握。
- 当前入口：[安澜操作台](http://47.93.218.52/anlan/console)。刷新后选择本机ignored `.runtime/aliyun-console-access.json`；也可用原演示访问令牌。新建任务即使用DeepSeek，旧offline材料保留历史。详见[P8交接](phases/phase-08-console/handoff.md)、[访问/运维](phases/phase-08-console/deployment.md)。
- 线上实际模式：材料和事件核查均为deepseek_live / deepseek-flash，服务端使用真实DeepSeek API；密钥只在服务器私密环境，不进入页面/仓库/报告。事实、知识、人员、区域及事件仍是SYNTHETIC合成示例；不能批准作业或控制报警，不具备图片/视频直接输入入口。
- 最新证据：P8-WP03的材料1次和两事件各1次真实调用均成功；P8-WP04随后针对“去哪里操练”完成一次真实材料回归，语义checked并返回地点追问。旧CI467、wheel98份源码/资源及部署故障模拟作为历史证据保留；新回归见[证据](phases/phase-08-console/evidence/materials-v2-release.json)。
- 当前发布：/opt/anlan2/releases/p8-materials-v2-budget-20261008，current已切换；复用已验证venv依赖，systemd仍为非root anlan2/127.0.0.1:8018。原PG13/现有库、原Nginx站点保持；本次未重置数据库、安装依赖或重载Nginx。
- P8-WP04地点语义回归：已发布 `/opt/anlan2/releases/p8-materials-v2-budget-20261008`。`materials-v2` 明确“去哪里操练”这类无区域/作业点的动作或疑问语句应被追问；隔离wheel仅含材料提示词、预算包与SQL011（SHA-256 `cd19ed1ac3c6adc2d8501e4751ed979cb59cb2015a1d02d52cdddcdb4c29876c`）。P8-WP03后来达到10/10，未重置或借用旧包；SQL011新增P8-WP04并保持总100/单包10上限。一次真实合成回归返回 `semantic_status=checked`、`materials-v2`、精确引用“去哪里操练”及地点含糊追问，消耗467 token；预算现为57/100、P8-WP04为1/10。定向18项测试及Ruff通过；本机无专用PG导致两项真实PG集成测试未运行，云端实际迁移、健康及一条请求已验证。详见[发布计划](superpowers/plans/2026-10-08-material-location-prompt-release.md)及[证据](phases/phase-08-console/evidence/materials-v2-release.json)。
- 模型预算：20260920-long-term-v1，57/100；P8-WP03已在后续使用中达到10/10，SQL011新增P8-WP04而不重置旧包，本包已用1次、剩9次。失败与预占计数，不隐式重试或借用旧包。P8-WP04本次467 token；更新后的累计token与金额未另行汇总，P1历史3次1184token另列。
- 云端PG是唯一真实调用预算写入方，本地相同authorization仍冻结。原46条attempt_id、状态、用量、错误、预占/完成时间已与首次迁移文件逐字段规范化比对，发布前后相同：[预算证据](phases/phase-08-console/evidence/live-cloud-budget-after.json)。SQL010与SQL011只增加P8-WP03/P8-WP04合法包名，不重置任何次数。退回本地live须显式单一账本交接，不能让两份账本独立花费。
- 历史实验归属：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9、P5-WP02=4、P6-WP03=8、P7-WP03=4、P8-WP03初始验收=3；P8-WP03后续页面使用达到10，P8-WP04地点回归=1。原感知失败0/2及后续最低2/2不改写，未知旧字段根因保留。
- 版本/恢复：旧offline材料不可续写或新增事件/核查，既有结果仍可按currentness/revision记反馈；新建材料进入DeepSeek模式。成功响应的同request_id重放不新增调用；模型返回后checkpoint落盘前中断，显式recover可能再调用并计次，页面已提示。
- 保留的失败：历史缺浏览器/移动端溢出/一次未完成CI/软件源超时/pgvector构建/ident拒绝/重启首次未就绪等均保留；WP03初始合同red、历史模式隔离red、旧打包校验器固定SQL数失败、SSH认证失败、浏览器重连时按钮仍禁用导致一次选择超时也保留说明。后续成功不用于臆断所有失败根因。
- 仍开放：[Q-P6-001](quality-items.md) Judge误判与Q-P6-002并发409；Memory/多职责无已证实质量收益，Mem0仅静态比较。当前HTTP/IP/模拟身份，TLS、生产认证/SLA、真实现场/设备、Docker/Compose和远程GitHubCI未验证。P8-WP03初始3次及P8-WP04地点回归1次仅证明有限接线与该单一样本，不证明模型全面可靠。
- 用户改动：16路径32行译文、.idea和learning-log整文件保持unstaged；不恢复或整体stage工作树。旧项目只读。AI编写/运行不升级本人掌握：[能力矩阵](capability-matrix.md)、[学习记录](learning-log.md)、[P8学习五题](phases/phase-08-console/wp01-learning.md)。
- 下一步由用户亲自操作或提出具体小增量；本包已交付，不创建自动化或无目标新阶段。原自动化2-0已删除，长期授权不等于无限扩栈或无限付费。

冷启动：适用AGENTS → 本状态 → P8交接/部署与ADR014 → Git/index及最小必要smoke。云端服务保持运行；本地PG17/55432仅供offline学习和独立测试授权，系统PG10未动。管理凭据只在连接进程中使用，不打印、不提交；不要重复bootstrap/activate，不为证明完成重复付费实验。
