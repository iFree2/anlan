# WP04可靠性：保留并发409，零模型请求

## 只读SQL回看

[sql-analysis.json](sql-analysis.json)实际连接既有PG17，事务read_only=on，按唯一授权、合成tenant/user和4个原始review ID进行LEFT JOIN/聚合。新2条completed/succeeded及needs_verification，共5843token；旧2条invalid_output/failed无反馈，共5072token。换无关tenant返回0行，前后生产预算均42。不新建事实/预算表，不因失败缺反馈将其排除。这是观测到的前后差异，不证明某个Prompt字符造成旧失败。

## 同任务本机读取实验（并发能力未通过）

新ignored随机token配置，本任务自建回环HTTP进程，移除模型凭据，预热后读一个固定材料快照。每组24请求，全部样本与失败保存在[benchmark-v1.json](benchmark-v1.json)。输出status=failed正确保留；未重跑刷分，未删409，也没有把部分成功称作承压通过。

| 并发 | 200且快照一致 | 409 | 全样本p50 ms | 全样本p95 ms | max ms |
|---|---:|---:|---:|---:|---:|
| 1 | 24 | 0 | 77.516 | 194.168 | 233.198 |
| 4 | 13 | 11 | 120.106 | 237.632 | 259.209 |
| 8 | 11 | 13 | 204.0345 | 324.894 | 330.456 |

没有超时或500。非授权读取401，本次服务已停止，PG保留，预算42→42。每请求时延从获得本地并发名额后计时，排队时间只计入整组墙钟；requests_per_second是尝试吞吐而非成功吞吐。p95用nearest-rank，包含失败，不能拿它证明成功请求生产延迟或模型SLA。单机同进程、预热、小样本、固定顺序，没有资源饱和或跨机规模结论。

静态核对WorkflowService.get获取Registry.locked，PG非阻塞pg_try_advisory_lock，TaskBusy经API映射409；与同任务并发冲突一致。登记Q-P6-002，保留锁边界不为性能漂亮而删锁，也无引入Redis/MQ/队列的证据。历史PG异常退出/P3长暂停/P5导入失败触发根因未被本实验解释。

测量红绿验证4项（非法并发、超时/500/快照改变均保留失败）；独立审查提出进程退出超时兜底缺口，cleanup-red复现，新增仅对本任务Popen的terminate/wait→kill/wait及状态记录，cleanup-green 5通过。真实v1本就已正常停止，未因补清理代码重复承压实验。

最终本地CI、当前wheel和冻结回归以本目录ci-final/clean-service/legacy-gate报告为准；性能失败和开放质量项必须与工程Gate同时展示。
