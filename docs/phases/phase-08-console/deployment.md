# 阿里云操作台访问与运维

2026-10-07用户授权部署已运行验收。入口：[安澜操作台](http://47.93.218.52/anlan/console)。

后续用户要求接入真实DeepSeek的P8-WP03已完成本地接线，尚未发布，正在等待SSH连接。下列模式表仍描述当前线上；不要仅因仓库已有deepseek_live代码就认为公网页面已切换。详见[WP03验证](evidence/live-verification.md)。

## 如何开始

页面点击“选择演示配置”，选择本机ignored文件：

~~~text
D:\src\agent学习\安澜2.0\.runtime\aliyun-console-access.json
~~~

这是随机演示访问令牌的配置，不含SSH或数据库管理密码。文件只在浏览器本地读取，令牌仅内存；刷新后重新选择，业务状态仍从云端PG读取。不要把文件加入Git或复制其内容到公开资料。

最近任务已准备“操作台上手试件A”，故意缺少位置与方式。依次填写两个字段并提交，观察v1→v2→v3、追问减少。然后点击未戴安全帽/气体浓度异常→“核查所选事件”→选择并保存人工反馈；修改材料后观察旧结果过时。

材料offline、事件核查scripted_double，事实/知识使用实际本地查询与PG/BGE。模拟人员/区域由服务端演示配置固定，页面选择任务用于合成关联；尚未自动判断材料位置文字与实际区域是否一致。业务时间固定为2026-09-22示例时点，不作为当前现场事实。

## 当前部署

| 项目 | 采用值 |
|---|---|
| OS / Python | 阿里云Linux3 / 独立Python3.13.3；系统3.6未替换 |
| 发布目录 | /opt/anlan2/releases/p8-console-20261007；current符号链接 |
| 服务 | anlan2-console.service，用户anlan2，127.0.0.1:8018 |
| 外层入口 | 原Nginx80新增/anlan/，主配置及原网站未覆盖 |
| 数据库 | 原实例PG13.23 / 新anlan2_console，随机应用角色anlan2_console_app |
| 知识 | pgvector0.8.6 / 固定BGE512维模型与三份示例制度 |
| 私密配置 | /opt/anlan2/shared/app.env（root600）、console.json（应用用户600） |
| 实际模式 | 合成数据、offline/scripted_double；没有云端模型密钥或live页面入口 |

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

上述迁移结论沿用部署交接；公开报告保存汇总与冻结结果，尚无云端逐条字段摘要比对。bootstrap仅用于首次部署，已有attempt_id冲突会被忽略；不要为验收重复执行它，也不要把它当作账本同步/修复工具。

## 运行验证与限制

[公网浏览器](evidence/cloud-browser-v1/report.json)九项通过；三查询均ok，反馈/材料版本/两事件在服务重启前后快照完全一致：[重启报告](evidence/restart-result.json)。首次重启校验在服务就绪前失败，原件保留；不声称无停机或SLA。原网站200且内容摘要不变：[HTTP核对](evidence/cloud-http.json)。本包真实模型请求0，历史质量项仍开放。

公网当前HTTP/IP；未配置域名/TLS、生产认证或真实现场接入。Docker/Compose/远程GitHubCI仍未运行。本次为实际原生Linux云端学习部署，不把测试通过升级为生产承诺或本人掌握。
