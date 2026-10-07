# 阿里云操作台访问与运维

2026-10-07用户授权部署已运行验收。入口：[安澜操作台](http://47.93.218.52/anlan/console)。

后续用户要求接入真实DeepSeek的P8-WP03已完成发布：材料及事件核查均为deepseek_live / deepseek-flash，实际3次请求全部通过，见[云端验收](evidence/live-cloud-acceptance.json)和[账本核对](evidence/live-cloud-budget-after.json)。本地默认启动仍为offline/scripted；两种环境的模式不能混称。

## 如何开始

页面点击“选择演示配置”，选择本机ignored文件：

~~~text
D:\src\agent学习\安澜2.0\.runtime\aliyun-console-access.json
~~~

这是随机演示访问令牌的配置，不含SSH或数据库管理密码。文件只在浏览器本地读取，令牌仅内存；刷新后重新选择，业务状态仍从云端PG读取。不要把文件加入Git或复制其内容到公开资料。

点击“新建任务”填写四项合成材料，提交会调用DeepSeek；随后可模拟未戴安全帽/气体浓度异常→“核查所选事件”→保存人工反馈。每次创建/补充/修订分析和新事件核查可能计1次请求，失败也计数，显式恢复也可能再次计次。本包当前剩7次，累计49/100；不要为查看结果重复点击发起核查。

可以只读查看“SYNTHETIC：DeepSeek云端验收试件A接缝”，已有真实材料分析和两类核查/反馈。旧“操作台上手试件A”等offline材料保留历史，不可续写或新增事件/核查；新任务使用当前DeepSeek模式。材料语义与事件归纳已使用真实模型，事实/知识仍使用合成记录与PG/BGE。模拟人员/区域由服务端配置固定，尚未自动判断材料位置文字与实际区域是否一致。业务时间固定为2026-09-22示例时点，不作为当前现场事实。

## 当前部署

| 项目 | 采用值 |
|---|---|
| OS / Python | 阿里云Linux3 / 独立Python3.13.3；系统3.6未替换 |
| 发布目录 | /opt/anlan2/releases/p8-deepseek-20261007；current符号链接 |
| 服务 | anlan2-console.service，用户anlan2，127.0.0.1:8018 |
| 外层入口 | 原Nginx80新增/anlan/，主配置及原网站未覆盖 |
| 数据库 | 原实例PG13.23 / 新anlan2_console，随机应用角色anlan2_console_app |
| 知识 | pgvector0.8.6 / 固定BGE512维模型与三份示例制度 |
| 私密配置 | /opt/anlan2/shared/app.env（root600，含服务端DeepSeek密钥）、console.json（应用用户600） |
| 实际模式 | 合成数据、deepseek_live / deepseek-flash；材料与事件均已真实调用 |
| 依赖与回滚 | 新发布app目录装载已验证wheel；venv复用旧发布，旧目录必须保留；私密备份在shared/before-p8-deepseek-20261007 |

已有postgres/multi-agent-master/anlan_db保留。只为新库/角色增加本机SCRAM HBA例外，旧规则和备份保留，不重启PG。仅新增匹配版本开发包，原PG版本未升级；pgvector关闭可选LLVM bitcode，动态库/SQL/向量检索实际运行。

## 运维与回滚边界

通过用户自己的SSH管理通道执行，不在文档保存密码：

~~~bash
systemctl status anlan2-console
systemctl restart anlan2-console
journalctl -u anlan2-console -n 50
nginx -t
~~~

停止这个应用使用systemctl stop anlan2-console；不停止已有PG、Nginx或其他业务。要撤回公开入口，仅移走本包新增的/etc/nginx/default.d/anlan2-console.conf，在nginx -t通过后reload；保留数据库、历史和发布包。HBA备份/opt/anlan2/shared/pg_hba.before-console为私密服务器文件；回滚时只去掉本包新库/角色行，不用旧备份覆盖随后其他人的修改。

预算已从本地切换到云端唯一生产账本，原46次/100（44成功、2失败、无pending）完整保留，未重置次数。本地PG相同authorization只保留历史，触发器禁止写尝试；其他测试授权不受影响。本地offline演示仍可用，旧本地live预占会被拒绝。后续真实调用应在云端账本预占；切回本地前需要显式单一写入方交接，不可同时开放两份账本或回退预算。

WP03发布前后将原46条逐字段规范化比较，原attempt_id/状态/用量/错误/预占与完成时间均与首次迁移导出相同，见live-cloud-before.json及live-cloud-budget-after.json。新增P8-WP03三条成功记录，共6342token，累计49/100，47成功/2历史失败/0pending；上限不变。bootstrap仅用于首次部署，不得重复作为账本同步/修复工具。

WP03激活脚本为deploy/aliyun/activate_deepseek.py，prepare验证wheel并保存私密配置，activate从stdin接收密钥并只重启本应用。切换PID2143209→2153128；未安装新依赖、重置数据库或重载Nginx。失败路径在Linux临时目录用模拟服务检查了恢复，实际本次切换一次成功，未演练真实生产故障回滚。脚本为一次性发布，勿重复prepare/activate。

如需退回替身模式：先停本应用，把current切回/opt/anlan2/releases/p8-console-20261007，从私密备份恢复app.env（root:root/600）和console.json（anlan2:anlan2/600），再启动并验证就绪；若配置后来有变，先逐项合并，不能盲目覆盖。保留当前数据库、全部49条预算、SQL010及本地冻结规则。回滚应用不退还已用次数，新deepseek_live任务保留历史。

## 运行验证与限制

WP01/WP02的[公网浏览器](evidence/cloud-browser-v1/report.json)九项及[重启报告](evidence/restart-result.json)作为历史保留。WP03实际浏览器创建材料、两事件DeepSeek核查、保存反馈、刷新重连恢复通过；当前原网站200且摘要不变，旧任务快照不变，见[live-cloud-acceptance.json](evidence/live-cloud-acceptance.json)。真实请求3次成功，不扩大为模型质量普遍保证。历史质量项仍开放，不声称无停机或SLA。

公网当前HTTP/IP；未配置域名/TLS、生产认证或真实现场接入。Docker/Compose/远程GitHubCI仍未运行。本次为实际原生Linux云端学习部署，不把测试通过升级为生产承诺或本人掌握。
