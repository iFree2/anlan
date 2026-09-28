# P6最终交接：工程Gate通过，接续P7

持续授权不变：同目录逐包实施/验证/保留失败/文档/提交后自动下一包；阶段工程Gate后再创建同目录GPT-6 Astra/high的P7任务。仅真正范围/破坏/业务副作用/输入/预算阻塞才问一次，独立工作继续。协调已有30分钟自动续接，不重复建；本任务唯一写入者。

## 最终状态（2026-09-28收束；9月27日验证原件保留）

P6-WP01=780558f、WP02=758573d、WP03=d188216；WP04最终交接提交以本文件当前Git提交为准（git log -1 -- 本文件）。最终CI434 passed、0 skipped（84真实PG标记），88安装源码/资源SHA与CI一致，9资源/9旧CLI及新quality CLI，清洁两类HTTP/SSE/重启、原P5八检查和P4的9/6/3/2/61故障全部通过。九项P6 Gate见[evidence/wp04/gate-report.md](evidence/wp04/gate-report.md)。

**工程通过不等于并发性能通过或可靠Judge。** Q-P6-001保留六标签5/6的一错；Q-P6-002保留同任务1/4/8并发各24次中409为0/11/13，benchmark-v1保持failed。读取本来获取同任务非阻塞advisory lock，未绕开ADR002、未静默重试/删失败，也没有引入队列。SQL真实READ ONLY核对旧两失败与新两完成及反馈/token，错误tenant返回0。原P5Gate程序固定的质量字段是历史标签，本次只复用工程检查；当前质量项以P6报告/quality-items为准。

WP04零模型请求，PG42→42。P6新增10真实请求共12774token，累计42/100：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9、P5-WP02=4、P6-WP03=8。40succeeded/2failed/0reserved；总已知70746输入/9844输出/80590token，P1历史3次1184另列，金额未查。相同感知问题仍归P5-WP02，Judge文本实验不是绕限；P7调用前必须再读即时账本。

下一阶段按[计划](../phase-07-takeover-career/plan.md)/[验收](../phase-07-takeover-career/acceptance.md)，先首包接管演示与已知限制，随后有限Memory比较、小任务复用、多模态和如实求职素材。不自行换供应商/模型或拿真实员工素材；若具体步骤缺新授权只停依赖部分问一次，独立工作继续。本人操作/讲解证据只能用户提供，AI不能补造；个人练习不阻塞其余开发。

本任务的临时HTTP/Java已停止，PG17继续供接续。新shell scripts/dev-postgres.ps1 -Action Env。当前wheel .runtime/p6-final-dist，干净环境仍.runtime/p5-service-clean/venv，仅更新了项目包；.runtime/p6-service-config.json含随机token且已用于回放，不打印/提交，复现用新配置。Docker/Compose/远程CI未运行。

用户16路径32行译文和.idea保持unstaged。learning-log继续原P1→P5排序，P6四条附后；整体不提交。独立wp01—04-learning均可查。去掉本任务P6目录/条目后与.runtime/p6-wp01/learning-log-before.md逐字节一致，证据见evidence/wp04/user-preservation.json。原P5学习重排和P5WP03入口也是用户未提交区，不能覆盖。长期协调已有30分钟续接id=2-0，勿重复创建或并行改码。本任务后续停止代码写入，由同目录新P7任务唯一接续。

## WP01历史完成快照（当前累计预算见最上节）

原Q-P5-001两次invalid_output、0/2、5072token原件保留。发现SYSTEM的notice句号歧义且无完整Schema；改为Pydantic自动生成Schema和精确JSON字面量。此为明确可证伪假设，不是已证明的旧字段根因。安全诊断type/loc将任意额外字段名脱敏，网关外层JSON/信封/超大响应固定错误标识；串行锁内复制、每次重置。严格应用验证/报警/预算归属没有放宽。

新增两次真实请求（每类一次）2/2有效，见[evidence/wp01/live-report.md](evidence/wp01/live-report.md)。两链真实PG/BGE/模型候选及模拟反馈/revise/stale完成，后续新revision重核明确替身。Q-P5-001最小候选阻塞关闭，不能宣称泛化/生产/现场/未知场景真实验证或本人掌握。旧0/2与原P2/P3/P4无增益/引用问题/未知根因继续保留。

PG唯一账本累计34/100：P2-WP02=6、P2-WP04=6、P3-WP03=9、P4-WP02=9、P5-WP02=4。32 succeeded、2 failed、0 reserved。相同感知问题仍用P5-WP02，不能换阶段重置。新授权累计65109输入/8550输出/73659总token，P1历史3次1184另列，金额未查。本包实际实验当前进程只读既有docs/DS.txt且不输出，子CLI不继承模型凭据。

红绿与独立只读审查见[verification](evidence/wp01/verification.md)，最终CI状态以ci-final.json为准。本包只改网关诊断/感知提示，未修改业务PG状态与锁边界。原P5 Gate/清洁wheel是旧版本证据，不用旧wheel冒充本次源码。

## 原在途接续计划（WP02—04现已完成）

下一包[WP02](wp02-plan.md)：显式来源/SHA与合成反馈、Badcase、开发/留出冻结、只读查看/录制回放/真实复跑隔离。WP03有限Judge与单多复测，WP04真实故障/并发/延迟及SQL分析，均按主plan范围细化。此处为在途计划；P6阶段工程Gate现已通过，结果见最上节。

用户16路径32行中文译文仍保留，.idea不动。learning-log继续P1→P5原排序后新增P6入口和WP01条目，完整文件不提交；本次原始备份.runtime/p6-wp01/learning-log-before.md可逐字节验证。独立wp01-learning.md可提交。原用户变化映射与P5交接保护要求继续有效。

新shell先scripts/dev-postgres.ps1 -Action Env，PG17.11在127.0.0.1:55432；不碰系统PG10。无Docker/Compose/远程CI事实不变。实际模型端点/模型/20秒/1024输出token/无重试与合成数据约束继续。

## WP02历史完成快照

新增workflows/quality.py和interfaces/quality_cli.py，离线inspect/replay无HTTP/PG导入，显式来源SHA/合成边界、file/family/event分组和不可覆盖报告。evals/quality-v1冻结11项，6dev（2旧无输出不可回放）+5合同留出，非模型泛化留出。重复unknown的开发Badcase由集合去重造成误接受，补长度验证后开发5/6→6/6，留出首次5/5。源文件跨split和畸形CLI空报告两漏洞已红绿修复。最终44离线/此前54含13真实PG相关检查；账本34不变，未读模型凭据。接WP03计划先冻结6条Judge可核对标签，独立文本实验最多8请求，不能复用它追加感知问题。

## WP03历史完成快照

可信宿主白名单新增P6-WP03（旧P3/P4默认与CLI不变），不是追加感知预算。evals/judge-v1冻结两包六标签，不向模型传gold；观察是手写合成夹具。真实8请求、Judge5/6，保留unknown/expired误判unsupported为Q-P6-001；两单/双各2/2接受，双token+87%/模型阶段延迟+107%，无本组收益。固定同候选audit消融不发请求且不改变候选。报告evidence/wp03/live-v2.json。

PG当前42/100：新增P6-WP03=8/10；P5-WP02仍4/10；40succeeded/2failed/0reserved。累计70746输入/9844输出/80590总token，P1另列1184。最终账本读取失败会保留已知预占下限、总数未知而非零，审查红绿及独立复审通过；相对runpy启动首轮在指纹阶段失败，PG34未变，修复后才真正调用8次，旧失败证据保留。44相关测试通过。WP04现已完成，结果与当前累计预算见最上节。

## 2026-09-28续接核对

未发现适用AGENTS或源码变化；最终CI源码指纹仍一致，未重复模型实验/全量测试。独立静态审查确认工程Gate没有冒称性能/Judge能力通过。首次账本读取BudgetUnavailable，项目pg_ctl确认未运行；仅启动项目PG17后核对42/100、无reserved，系统PG10未操作。证据resume-budget-20260928.json；未推断停库原因。用户32行译文、学习排序和.idea继续保留。
