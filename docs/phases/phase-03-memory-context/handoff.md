# P3阶段交接：工程Gate通过，启动P4

2026-09-21。依据[Gate报告](evidence/wp03/gate-report.md)。长期授权按路线图自动执行到底，常规范围/练习不再暂停；下一阶段同目录GPT-6 Astra/high，读取仓库事实后直接做首包。

## 当前可运行能力

P1 Graph/PG恢复与P2事实/知识/三工具模型循环保留。P3增加`memory.py`、SQL004、独立`memory_cli`：两类SYNTHETIC枚举偏好，来源登记/归属/hash、candidate确认拒绝、修正、显式冲突、TTL、删除tombstone与历史防回退。PG事务同写当前状态和审计；删除后不恢复，普通列表只读本用户有效active。

`context.py` v2在最大24000序列化UTF-8字节内组装固定边界/指引、当前材料与知识问题、事实/未知/来源，再放有效知识原文、有效偏好和历史。必需部分超限不请求；偏好不能改权限、批准或隐去未知。`assets/hot-work-review-v1.md`是版本化业务指引，不是可执行Skill平台。

`review.py`/`review_cli.py`提供固定三只读工具采集＋一次模型综合。输出逐条claim引用、完整unknown清单及presentation。引用只可来自实际入上下文的片段，非法候选保留为rejected_candidate，仍不修改Graph。身份先于依赖，采集期间变材料拒绝混版，最终材料变化标记stale。该固定采集基线与P2模型自主选工具循环不同；P4对照请沿用相同输入、采集口径和评分。

## 验证、用量和失败

最终228项全量通过（34真实PG），ruff通过。P3冻结Gate：8上下文场景＋9同任务替身综合策略＋24命令跨进程Memory；独立综合CLI跨进程/越权/已有偏好通过。P2冻结回归11/11含Jaeger平台与真实本地编码；均在python -O下运行且新增请求0。

P3真实实验9次/20465token，固定P3-WP03、每任务最多3次/共3任务；HTTP/Schema全成功，应用候选接受6拒绝3。累计授权`20260920-long-term-v1`为21/100（P2-WP02=6、P2-WP04=6、P3-WP03=9），已知输入35509/输出4774/总40283token，无未完成reserved。P1历史3次/1184token单列，金额未查询。唯一权威仍PG model_budget_authorizations/model_budget_attempts；每包10/累计100是保守次数上限，失败/未知也计数，禁止重启/子任务重置、退款或先请求后改账。

[真实消融与AI逐条复核](evidence/wp03/live-report.md)：无/有记忆都接受2/3，有记忆增加755token且未改善质量；去知识原文节省token但丢依据。三份拒绝候选其实正确指出材料注入不构成授权，却因合同没有材料引用类型、该主张无来源而整体拒绝。已接受候选仍含“仅返回来源/原文可能裁剪”等不准确状态说明和偏离主题的额外引用。presentation字段遵从不是实际呈现质量。全部developer_seen，未证明泛化，无独立人工金标；本人掌握待验。

修复保留：旧反馈跨来源回退、问题漏传、trace状态缺失/早期失败警告丢失、reason-only事实评分假通过、共享账本增量归属。WP02一次约13小时墙钟停顿使重复call_id测试超时，复跑通过但根因未确定。P2本轮首次漏加载Jaeger Env，初始化失败0场景，补Env后11/11。P2混合无收益、摘要次要主张缺引用、PG非正常退出原因未明不变。

## 环境/复现

```powershell
# 同目录；PowerShell7运行Jaeger脚本
scripts/dev-postgres.ps1 -Action Env
uv run python -m anlan.memory_cli init
uv run python -O evals/phase03_gate.py --output .runtime/p3-new-gate.json
scripts/dev-jaeger.ps1 -Action Env
uv run python -O evals/phase02_gate.py --output .runtime/p2-new-gate.json
```

Gate输出必须使用新路径。PG17.11 127.0.0.1:55432，系统PG10未改；必要时项目脚本Status/Start。Jaeger2.21.0在16686，内存非权威；Start已有实例会直接返回，新终端仍单独执行Env。预算用`uv run anlan budget-status`读取。固定事实/知识复现as-of=2026-09-20T12:00Z，area-001实际于2026-09-21北京时间08:00过期是预期，不能改冻结日期。BGE缓存/manifest在.runtime/embeddings。

用户指定凭据docs/DS.txt被忽略且未提交；真实实验仅临时读进当前子进程环境，不输出密钥。`DeepSeekToolModel`支持可信work_package参数，`DeepSeekReviewModel`仍固定P3-WP03；P4先接正确包号并测试，不能直接复用此类误占P3剩余1次。P1材料默认仍P2-WP02，P4真实调用同样要显式归属。

首包[WP01](wp01-handoff.md)、[WP02](wp02-handoff.md)、ADR006/007、能力矩阵与学习记录可定位细节。原14文件中文注释/docstring共32行与.idea仍未提交，当前阶段不再并行改代码。不要整文件提交用户翻译；没有新依赖，沿用uv.lock。下一任务读取[P4 plan](../phase-04-multi-agent/plan.md)/[acceptance](../phase-04-multi-agent/acceptance.md)，检查Git和最小smoke，直接执行P4-WP01，不重建Graph、数据库、工具或Memory。
