# 公开安全生产语料候选首包设计

2026-11-22；任务A独占范围。设计门禁采用本任务明确指定的自审后继续，不提交、不部署；总协调窗口集成复验。

## 选择与边界

选定版本化元数据 + 无网络离线回放/导入校验。备选一是自动爬取网站，许可及网络信任面过大；备选二是直接进入现有RAG发布链，缺领域人工审核及文控授权，不适合首包。首包不提供HTTP客户端、URL下载器、SDK/数据集脚本执行或检索发布接口。

真实来源仅登记官方事故调查报告、BAAI发布方数据卡和ModelScope发现入口。联网核实来源、revision、许可与访问条件；缺少明确全文使用边界时只留URL、元数据及观察hash，不复制正文。网页发布日不等于不可变revision；HTTP字节hash只证明特定观察，不证明后续远端未变。

## 合同

`src/anlan/knowledge/sources/`仅新增独立模块。Pydantic frozen/extra=forbid合同含schema_version、manifest_version、publisher/source_url/retrieved_at/upstream_revision、license及证据、content_kind、validity、review_state=candidate。无法确认的版本/hash使用null，明确原因，不伪造。许可unknown可登记但不可导入。证据对象区分web观察与原字节快照。

真实来源URL仅允许HTTPS精确主机白名单 www.mem.gov.cn、huggingface.co、modelscope.cn；拒绝凭据、端口、IP、片段、query、控制字符、反斜线及编码路径。2026-11-23总窗口审查后补充：合成样本必须同时具有access=offline_fixture、content_kind=synthetic_case、data_origin=project_fixture，其来源与许可证据只能使用synthetic://public-pilot/<name>.txt；真实来源data_origin=public_source，不能使用synthetic URI，夹具不能使用HTTPS定位符。所有redirect直接拒绝，因此不需要解析或访问重定向目标。此为离线输入校验而非网络SSRF沙箱；未来下载须另设计DNS解析/连接绑定及期限。

离线导入消费已由宿主取得的bytes及回执URL/status/content-type；必须URL等于登记地址、status=200、无redirect、无content-encoding，仅UTF-8 text/plain且最大64KiB、固定SHA256精确匹配，license evidence明确允许该内容再分发且版本固定。只返回candidate receipt与hash，不写全文、不产生DocumentIR、不接现有知识/工作流。人工更改许可字段不等于法律授权，宿主必须审核证据；本工具做合同一致性检查。

`scripts/curate_public_safety_corpus.py`提供validate与replay，拒绝覆盖输出，不联网。replay只支持清单同目录之下的普通本地文件，拒绝路径穿越、符号链接/目录、超长读取，CLI输出只有候选摘要。真实候选全为metadata_only；仓库仅有明确标识的SYNTHETIC合成小夹具及其hash用于回放，非人审金标、非未见集。

## 验收与自审门禁

先写tests/test_public_safety_sources.py并观察RED，再实现。分别验证清单缺字段/未知字段/时间/版本、恶意URL及redirect、大小/类型/hash/许可缺失、只读candidate状态和CLI离线回放。真实网络证据单列不参与测试；不借替身声称真实下载成功。

自审已核对：事故报告类别只允许accident_case，validity固定not_enterprise_authority，无自动published状态；未知许可保留candidate；无网络下载；证据hash与全文hash不同；无既有核心文件修改。设计无待填项，允许进入小计划。独立实现审查在交付前执行。
