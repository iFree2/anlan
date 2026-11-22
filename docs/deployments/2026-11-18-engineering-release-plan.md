# 工程增量整合发布：设计与执行门禁

授权：本轮读取新AGENTS.md，用户已授权本地验证完成后自动发布既有ECS。当前HEAD ae23500含已上线业务问答，任何制品须与当前整合源码逐文件核验。目标固定47.93.218.52、anlan2-console、/opt/anlan2，既有业务与账本保留。

## A/B 当前基线与目标

只读SSH已校验pinned host，线上current=/opt/anlan2/releases/business-query-20261117，wheel fd2c20866774f2c03a3e3ce6a5e3cd9ea79fc29c3c04b03c5ad1ef67c9b975e0；SQL021在内、无022/023，四类旧pending均0（P13队列另补核验），模型历史146条，服务active/两角色与legacy配置。服务配置、环境、systemd均只记录SHA，不输出正文。证据ignored .runtime/engineering-20261118/ecs-before.json。

目标是发布当前业务问答加上一轮已验工具/知识/评测/动态MCP库。非目标：注册真实企业MCP、开管理API、改角色令牌/预算、真实模型实验或新增普通对话功能。022/023是显式管理初始化迁移，本次不自动应用，生产迁移集合维持原值；模块存在不等于对普通用户启用。

## C 设计与所有权

1. 先保护当前191个modified/untracked文件hash；当前工作树不reset/clean/整体stage。基于当前HEAD整合源重新构建并全量非live验证。2026-11-19中断恢复：重建得到同一9b8制品，逐文件匹配当前src，含业务问答/SQL021；不能仅凭旧报告日期判定内容缺失。当前应用完整非live1673 passed/946.24s，426项指纹未变；新发布helper单独验证。
2. 发布源码通过独立临时Git索引形成codex/发布分支提交，不切当前分支、不改当前index。只收录上一轮owned清单中经过hash确认的src/tests/evals/样例与配置；不收录原用户dirty文件/私密runtime。当前HEAD的业务问答作为父提交保留。应用提交和发布操作提交可分开记录，wheel每个源码/资源必须与应用提交blob逐字节一致。
3. 新helper独占deploy/aliyun/release_engineering.py，测试tests/test_engineering_deployment.py；不修改旧helper。BASE固定业务问答release，NEW工程独立release、独立备份路径；避免旧helper无条件重跑021。模块复用旧query helper只读/备份工具，切换/回退语义使用reviewed maintenance helper。
4. prepare：artifact pin/路径与依赖签名/全模块导入/原配置/当前release校验，读取全部pending及P13 queued/running jobs/attempts；PG原生dump+list验证、配置/环境/systemd备份，保存私密逐行摘要；解包到新目录，复用已兼容venv与examples，不改依赖/认证/现有事实数据。内容相同旧表保持逐行，模型ledger精确不变。
5. activate：复验备份与配置、基线行与quiescence，停止服务后再核验，原子切新release/启动，健康与三身份/匿名/私聊隔离/原问答回归；不应用021/022/023。任何stop之后失败进入维护应用，绝不自动恢复旧写应用或DB。
6. 线上验收采用更严格的零业务写入方案：只读HTTP、既有业务问答历史回读与身份隔离、新工具/知识/评测库纯本地合成probe与模块/schema导入；不计算新问答、不提交proposal、不创建会话/消息/查询审计。不自动创建MCP管理身份或对外服务。全部旧行/数量、ledger/packages/statuses精确不变，报告称saved-query readback，不称新问答计算或模型质量验收。
7. forward：只能维护态恢复该已验候选；校验既有审计为多重集子集、配置/备份/制品指纹。不drop数据、不退预算、不降目录代次。上线后记录源码提交、helper提交、wheelSHA、运行PID/版本、去敏证据。

依赖与helper准入补充：本地及只读远端六项实装版本一致（mcp1.30.0、pydantic2.13.5、fastapi0.141.1、psycopg3.3.6、langgraph1.2.11、httpx0.28.1），prepare/activate重核。复用的query/collaboration/preflight helper须固定文件hash，不能只按路径信任；候选全模块用目标venv离线导入。共享venv不原地升级。

prepare初始配置/环境/systemd指纹必须在备份前捕获；备份后、解包probe后和stop后switch前重核现用与备份对应初值，不以末尾新指纹合法化中途漂移。任何stop后失败须实际验证维护503再报告maintenance_verified，维护失败明确recovery_failed。

## D 审查清单

- [x] 不覆盖已上线业务问答；当前HEAD已纳入基线。
- [x] 身份/审批/告警/模型调用边界保持；默认不启用动态管理或022/023。
- [x] 当前工作树与用户原改动保护；独立索引/提交不整体stage。
- [x] 独立release_review设计审查通过；日期判断已改为blob/artifact准入，实装依赖/helper指纹、完整pending、受控追加及维护回退要求已补入。
- [x] helper失败注入RED/GREEN及独立复审通过：42 passed、Ruff通过，两项Important关闭。

## E–I 顺序和验收

- [x] 当前合并最小基线83 passed/3.18s，已保护191路径；不是旧1673结果直接外推。
- [x] 新helper按上述边界测试先行；独立源码审查关闭critical/important。
- [x] 当前整合完整非live回归、Ruff、wheel离源码导入/资源/兼容CLI；新增测试与源hash在命令前后核对。
- [x] 应用/操作提交与制品固定，remote只读二检、上传到新路径、prepare备份完整验证。
- [x] activate与实际线上验收，日志、旧行和预算指纹均保留；本次未触发维护回退。
- [x] 发布记录和去敏证据已保存；状态/交接同步，工程安装与未验证质量边界分开。

部署完成后再进入下一开发增量，避免验证期间并发修改同一源码。普通实现细节自行处理；若出现真实外部权限或业务配置决策再给证据与选项。
