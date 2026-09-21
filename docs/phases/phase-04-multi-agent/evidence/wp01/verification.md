# P4-WP01 验证与限制

2026-09-21。确定性职责分支，不是多模型自治。未读取模型凭据，PG生产预算21→21，新请求0。

## 可复现证据

- 冷启动40项通过，含真实PG恢复：[cold-start](../cold-start.xml)。
- 核心及审查后23项定向通过：[final-cancel-green.xml](final-cancel-green.xml)；全量初次250项通过：[pytest-final.xml](pytest-final.xml)，末端取消补测后全量251项通过（34真实PG、0跳过）：[pytest-release.xml](pytest-release.xml)。
- 同3个P3已见任务×原P3串行/受控串行/受控并行=9行，真实PG任务、BGE/pgvector、事实文件与Memory；全部证据/上下文/替身候选一致：[comparison-final.json](comparison-final.json)。合成材料revision/run、时点、对象、知识和偏好相同；仅在三路送入综合前统一移除测量elapsed_ms，原始工具耗时保留。不是模型质量实验。
- 独立进程4命令：serial/parallel均完成、陌生用户拒绝、P4-WP01真实模型入口拒绝：[cli-utf8.json](cli-utf8.json)。
- ruff全仓通过，无新依赖、没有修改Graph/PG写连接或Memory写路径。

## 延迟与退化

固定执行顺序、每任务仅一次，本轮全量测试同时运行，存在资源竞争，不能视为基准或显著收益。采集总毫秒：

| 已见任务 | P3串行 | 受控串行 | 受控并行 |
|---|---:|---:|---:|
| current | 362.53 | 272.54 | 262.35 |
| expired | 413.75 | 415.03 | 518.70 |
| no-knowledge | 396.58 | 368.24 | 439.12 |

两例并行更慢，不声称收益；本地知识读取占主要工作，双分支增加编排和最终版本核对成本。候选相同仅证明固定采集工程等价，token未调用/不估造，未知与依据评分复用P3；无泛化或个人掌握结论。

## 失败与修复保留

首轮缺模块红测输出出现9个失败后，取消测试一直等尚未进入的依赖事件；人工中断该测试进程，未产出完整XML。后来将进入事件等待限制2秒；不虚构完整红测报告。初次green有5个测试替身clock绑定TypeError（[green-initial](green-initial.xml)），修正为staticmethod后16通过。后续集成2项红测见[integration-red](integration-red.xml)。

只读审查复现：deadline后cleanup吞外部取消、Memory阶段未监听取消/超时误报完成、Memory未冻结as-of。4项红测[review-red](review-red.xml)→22项通过[review-green](review-green.xml)。统一监督器覆盖Memory，父取消清理后传播，Memory使用副本固定时点。

审查追加发现最终材料检查期间取消未记录，1红[final-cancel-red](final-cancel-red.xml)→23绿。结束材料检查后单独读取显式取消事件；独立收尾预算不被误算工具deadline。

CLI首次子进程默认Windows编码，按UTF-8解码失败，0命令完成：[cli.json](cli.json)。显式传PYTHONIOENCODING=utf-8后4命令通过，保留原失败。P2/P3已有语义Badcase与未知故障根因均未覆盖或删除。

## 运行边界

工具0—3次预算按worker/area/knowledge预分配，失败不退款；分支运行+父Memory共享10秒默认deadline，随后材料检查最多2秒。初始身份授权先于依赖与计时；不是端到端数据库SLA。外部取消传播；显式取消返回已有证据及未知。受信任的异步适配器必须响应取消，Python不能强杀任意阻塞代码或底层只读线程；迟到结果不发布，无共享写入。来源冲突保存拒绝观察，汇合中标记未知，无多数投票。材料变化拒绝整个混版包。

复现：先scripts/dev-postgres.ps1 -Action Env，再用新输出路径运行 `uv run python -O evals/evaluate_parallel.py --output <new.json>` 与 `uv run python -O scripts/smoke_parallel.py --source <new.json> --output <new-cli.json>`。
