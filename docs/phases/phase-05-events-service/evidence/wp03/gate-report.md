# P5工程Gate通过；真实感知模型质量未通过

2026-09-27。P5-WP03完成本地FastAPI、可信身份、幂等start、持久重核取消、快照SSE、原生清洁启动与本地CI。阶段工程验收通过不代表生产部署、模型质量或个人掌握通过。

| 验证 | 实际结果 |
|---|---|
| 最终完整CI | [ci-final-v2.json](ci-final-v2.json)/[XML](ci-final-v2.xml)：400 passed、0 skipped，84项真实PG标记；lock/ruff通过，源码前后全集一致 |
| 初失败复查 | [resume-failure-regression.xml](resume-failure-regression.xml)：原PG/HTTP/错误输出相关16通过；未改超时/断言；初CI395项9失败仍保留 |
| API与运行故障 | 11项服务测试含真实本机HTTP、SSE断连重连、稳定snapshot ID、进程终止与恢复、持久取消；完整CI再次运行 |
| 干净venv/wheel | [clean-service-v3.json](clean-service-v3.json)：离源码python -I、两类事件/模拟反馈/SSE/重启、85个安装包源码/资源SHA与本次CI一致；只关闭本次服务 |
| 打包 | [wheel-final-v2.json](wheel-final-v2.json)：所有模块离源码导入、9资源字节、9个新旧CLI通过；干净环境依赖按uv.lock安装，后续只更新项目wheel |
| P5冻结 | [gate-final.json](gate-final.json)：8项检查全通过；两类事件→证据→合成反馈→revise→stale→新事件重核；新请求0 |
| 原P4冻结 | [gate-final.p4.json](gate-final.p4.json)：9串并行、6单双角色、3实际Java/MCP、2CLI与61故障全部通过 |
| 预算 | Gate和清洁启动均32→32，P5-WP03零真实请求、未读模型凭据；旧P5-WP02两次failed仍计数 |
| 环境限制 | [environment.json](environment.json)：无Docker/Compose，WSL状态失败；仅配置未运行的Compose、远程GitHubCI明确not_run |

独立AI只读审查检查业务/身份/恢复边界及验收脚本；指出完整源码集合和wheel证据绑定缺口后补红绿测试并复核。最终安装包85项与CI源码一致，新增文件/旧wheel/隐蔽请求/清理错误不能通过验真。

## 保留失败与未定原因

- [ci-initial.xml](ci-initial.xml)为395项9失败，至少4项明确是子进程无法导入build_graph；当前源码、pyc与新进程导入正常，旧HTTP临时日志已不可获得，历史触发原因未证明。没有声称已定位文件改写者或已修复该历史根因。复跑399及最终400全部通过；源码前后指纹用于拒绝混合版本，并不证明运行中绝无瞬时改写。
- clean-service-v1实际业务路径跑通，但脚本在服务未停止时清理其临时工作目录，PermissionError后仍留passed，属于假通过。原报告不改写、明确不计通过；cleanup-gate-red复现，随后关闭顺序与失败状态修正。v2尚未带安装包指纹，不能用于最终Gate；v3才完成完整绑定。
- source-binding-red保留新增文件/旧wheel混用防护的红测。发现旧安装service.py仅换行符字节不同后从当前工作树重建，只重装隔离venv的anlan，不重复安装依赖，不修改主venv或用户chat。
- 原P2/P3/P4的无增益、引用缺口、PG异常退出与长暂停超时等限制继续有效，旧原件/摘要不重写。

## 尚未通过的质量与个人验收

[Q-P5-001](../../../../quality-items.md)继续阻止最终完整感知能力验收：P5-WP02真实0/2、5072token，invalid_output具体字段根因未知；后补type/loc诊断只经替身验证。后续P6须基于明确假设有界诊断，沿用原P5-WP02已消耗2/10及PG累计32/100，不盲重试/换包绕限。不能用本工程Gate或合成反馈代替真实模型和本人实践证据。

全部验证基于保留用户原32行译文的工作树；提交只包含本包功能/工件，译文及用户重排的学习记录保持未提交。学习新条目位于P5章节，19条历史内容和顺序保留。原生清洁环境复用已声明的PG与模型缓存，不声称新建整个OS/数据库；材料通用取消、生产认证和真实设备接入仍未实现。
