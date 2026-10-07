# P8-WP02：用户授权阿里云部署

用户于2026-10-07明确要求完成后部署，并提供SSH/PostgreSQL连接信息。凭据仅用于进程内连接，不写仓库/报告/日志。此授权覆盖准备环境、独立数据库/应用角色、部署和运行验收。

只读检查：阿里云Linux3/x86_64，约2GiB内存，默认Python3.6.8，PostgreSQL13.23，Nginx80已有默认站点，数据库含postgres/multi-agent-master/anlan_db。选择独立/opt/anlan2、独立anlan2_console数据库与最小应用角色；不覆盖现有目录、数据库、PostgreSQL版本或其他服务。

- [x] 安装独立uv0.7.5/Python3.13.3，不替换系统Python；依赖由uv.lock导出并校验hash，使用当前wheel与静态资源。
- [x] pgvector0.8.6官方支持PG13+，安装匹配现有PG13的开发头文件后编译扩展；仅在新数据库启用，不升级/重启已有PG。
- [x] 按原本地缓存SHA传输BGE固定模型，只传必要合成示例文件，不上传docs/DS.txt、项目凭据或整个仓库/.runtime。
- [x] 使用指定PG实例创建独立数据库与随机应用密码；配置文件0600、进程非root、绑定127.0.0.1、systemd控制，单worker。
- [x] Nginx新增/anlan/前缀反代（既有default.d include），先nginx -t再reload，不覆盖主配置或默认页面。应用root_path与静态/API前缀一致。
- [x] 保留项目预算46/100历史，不因新数据库重置授权。云端仅offline/scripted_double、无模型密钥；部署后不自动添加真实调用。
- [x] 云端HTTP实际材料/事件/核查/反馈/修订/隔离/进程重启恢复；浏览器实际页面与固定模型/知识查验。报告不记录访问令牌。
- [x] 本地用户仅接收ignored操作台访问配置，SSH/PG管理凭据不入其中；更新启动/访问/运维/回滚说明与状态，保留未验证生产事项。

官方兼容依据：[pgvector v0.8.6](https://raw.githubusercontent.com/pgvector/pgvector/v0.8.6/README.md)、[uv Python管理](https://docs.astral.sh/uv/concepts/python-versions/)、[Paramiko客户端](https://docs.paramiko.org/en/stable/api/client.html)。操作助手Paramiko5.0.0安装在ignored独立venv，不加入应用依赖。

公网现有入口为HTTP/IP；没有用户域名与TLS配置。本包只提供合成学习环境，不表述生产认证/SLA。访问令牌为新随机演示token；管理凭据不交给浏览器。

执行状态已按验收与现有运行证据核对完成；最终只读复核见[evidence/final-readonly-verification.json](evidence/final-readonly-verification.json)。本人掌握仍待验证，预算逐条比对证据边界见[交接](handoff.md)。
