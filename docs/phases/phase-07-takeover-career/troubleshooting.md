# 接管排错路径

先保留失败目录，读取`report.json`的`failed_stage/error_category/steps`，再进入对应层。不要覆盖旧输出、删除失败或反复真实调用试运气。报告没有保存异常正文/密钥，详细业务状态在同目录合成工件中。

| 现象 | 最小检查与行动 | 不能据此推断 |
|---|---|---|
| 已有目录拒绝，退出2 | 保留目录并选新`--output-dir`；若原报告还在写，先确认旧进程状态 | 不能删目录重跑掩盖失败 |
| source_origin失败 | 核对`.venv/Scripts/python.exe`与`anlan.__file__`是否为当前`src/anlan`；使用README锁定环境 | 有源码SHA不代表旧wheel执行的是此源码 |
| budget_before失败 | `scripts/dev-postgres.ps1 -Action Status`；已停则仅启动项目PG；新shell执行Env；不要输出DSN | 停库原因未知；账本不可用不是额度0 |
| budget_after失败/账本不同 | 保留已经完成的步骤和已知快照；查唯一PG授权/attempt；当前总数未知就写未知 | 不退款、不重置授权、不因新阶段换包 |
| materials非零 | 看9条命令停在哪条；核对可信身份、task_id、revision、request_id与pending operation | task_id不可猜测不能替代归属校验 |
| TaskBusy / HTTP409 | 同任务非阻塞advisory锁竞争；先查原操作进度，用串行人工读取 | 不通过静默重试删去409，不称并发读取达标 |
| BGE/knowledge阶段失败 | 核对`.runtime/embeddings`本地模型与摘要、PG/pgvector及示例知识；按README准备缺失资源 | 不能用随机向量降级后声称语义检索通过 |
| candidate rejected / invalid_output | 检查固定Schema与精确notice、可信type/loc、unknown完整性和引用；区分外层JSON/信封/候选 | P5原失败没有字段证据，不能追认是notice导致 |
| stale_material / expired | 对照当前材料revision/run、来源水位和固定回放时钟；保留旧结果，显式修订/新绑定后再重核 | 过期不等于事实相反；不改变原报警 |
| replay缺输出 | 查看actual=not_replayable和原original_stop，保持缺口 | 标签匹配不能算模型回答成功 |
| 子阶段超时/取消 | 保留started步骤、已有子报告（可能不完整）；编排器先清理自己的进程树再读账本 | 合作式业务取消不是强杀任意外部扩展；本地进程清理不是远端撤回 |

## 两种recover必须分清

材料`python -m anlan recover --task ...`续接已登记但未完成的operation，沿用原run/revision边界。若供应商已处理而节点未落盘，材料恢复可能再次请求模型，仍须预占并计数，不能声称exactly-once。普通`show`是读取；waiting_input用resume，awaiting_review后的明确变更用revise。

感知`python -m anlan.interfaces.perception_cli ... recover <review_id>`必须先获得旧运行锁，保存interrupted/cancelled及原尝试归属，不自动重发模型。反馈仅三类事件判断枚举，不能改变材料、原始报警、权限或批准状态。

## 本包真实故障演示

[fault-checks-v1.json](evidence/wp01/fault-checks-v1.json)用独立子进程将DSN指向本机一个不可连接端口；项目PG保持运行。结果为退出1、budget_before失败、两个快照和增量均unknown、无子步骤启动、异常凭据不出现在报告。另一次对已有demo目录调用退出2，原报告SHA不变。复现用测试DSN，勿停止系统PG10或项目库制造故障。

独立审查的进程树问题通过无PG的“父进程启动延迟写文件孙进程”复现；原实现超时后仍产生文件，修订后不再产生。Windows采用[官方Job Object的子进程继承与终止规则](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)，启动屏障避免业务代码在纳入Job前启动。初修匿名Job名称参数的TypeError保留在review-green.xml，后续修正记录独立保存。

## 三个具体复盘入口

1. [Judge误判](../phase-06-quality-reliability/evidence/wp03/live-report.md)：观察unknown/expired、facts=null，不能推出“资质有效”与事实矛盾；正确冻结标签是uncertain。
2. [并发409](../phase-06-quality-reliability/evidence/wp04/benchmark-v1.json)：1/4/8并发各24次，409分别0/11/13；与get共享非阻塞独占任务锁一致，没有承诺修复或吞错误。
3. [重复unknown Badcase](../phase-06-quality-reliability/evidence/wp02/verification.md)：集合比较抹掉重复次数，新增长度约束使开发标签5/6→6/6；不改旧输出、不放宽Schema、不把不可回放算成功。
