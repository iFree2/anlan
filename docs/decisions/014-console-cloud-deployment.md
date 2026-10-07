# ADR014：轻量操作台与云端学习部署

2026-10-07，用户明确追加操作台并授权阿里云部署。接受。

采用同源静态页面＋原FastAPI/Graph/PG运行时；浏览器不是身份、任务或报警的权威。console_profiles是服务端合成接入配置，不从浏览器/模型接收tenant或事实对象。原始事件先提交，核查固定scripted_double，材料offline，反馈仍校验版本与当前性。

云端保留原PG13/已有库与站点；新增anlan2_console数据库和随机密码的anlan2_console_app角色、/opt/anlan2独立Python3.13与systemd非root服务，绑定127.0.0.1:8018；Nginx仅新增/anlan/反代。现有loopback ident认证不适用新角色，仅为新库＋新角色＋127.0.0.1/32增加SCRAM例外，原HBA备份和规则保留，reload而非重启PG。

迁移生产预算46次原始尝试（44成功/2失败/无预占）到云端PG；它是切换后的唯一真实模型调用账本，不新建可用次数100的空账本。原本地PG保留历史并使用只针对该authorization的数据库触发器拒绝INSERT/UPDATE/DELETE，测试授权不受影响。页面部署没有模型密钥或live入口，本包新增调用0。后续真实调用只使用云端账本；恢复本地写入前必须先停止云端写入并做显式账本交接，禁止两边独立花费或回退计数。

仍可在本地运行offline/scripted学习链。客户端令牌为随机演示token，只有ignored访问文件/页面内存；SSH/PG管理凭据未进入仓库、浏览器或报告。公网当前HTTP/IP、合成数据和模拟身份，不称生产鉴权/TLS/SLA；不在本包扩大供应商或真实设备范围。

失败取舍：软件源HTTP/HTTPS元数据超时，改用官方HTTPS RPM离线安装匹配PG13的开发包；不升级PG。缺RPM构建spec导致首次pgvector编译失败，保留编译器真实支持的安全flags并关闭可选LLVM bitcode后安装0.8.6；SQL/向量查询实际验收。历史质量项继续开放。
