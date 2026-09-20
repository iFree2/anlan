# P2-WP03：示例知识摄取与pgvector检索

2026-09-20，基于cf89f32，按长期授权连续实施。先完成可查询且有租户/时效/版本/撤回边界的知识增量，再接追踪平台，阶段Gate仍独立。

**Goal:** 对合成动火问题检索示例制度片段，明确来源、当前版本与未知；对简单向量检索和混合检索做同集对照，引用支持与命中分开报告。

**Architecture:** 版本化JSON示例制度按段落确定性切分，存入既有PG的独立knowledge表；本地中文BGE小模型生成512维向量，使用真实pgvector精确余弦检索。身份由入口注入，查询先做租户/授权/有效期/撤回过滤；引用由检索所得片段ID与原文构成，知识文本不作为系统指令。小样本先用摘录式有依据回答，不以自由摘要掩盖检索失败。

## 1. 可复现运行环境

- [x] Windows本机无管理员/C++/Docker/WSL。官方源码编译需要VS；官方列出的conda-forge当前win-64构建依赖PG16，不能用于现有PG17。采用明确标为非官方的社区PG17构建，只安装到本项目用户目录PG17.11，记录来源/版本/发布资产SHA256并做实际SQL烟测；不改系统PG10，不伪称官方二进制。
- [x] `scripts/install_pgvector.py`固定社区release 0.8.6_17资产及SHA256，拒绝覆盖不同既有文件，仅读取允许的DLL/control/SQL，不解压任意路径；`CREATE EXTENSION vector WITH SCHEMA public`仅项目开发库。证据保存版本/文件摘要与向量排序结果。
- [x] 主代理通过uv锁定fastembed与本地中文BAAI/bge-small-zh-v1.5，下载缓存放.runtime，不上传任何业务材料。记录实际模型文件哈希与版本，神经向量不可用时明确错误，不能用常量/随机向量冒充真实编码。

## 2. 知识合同与摄取

- [x] `src/anlan/knowledge.py`、`src/anlan/embeddings.py`、SQL003；`examples/synthetic/knowledge-v1/`保存明确SYNTHETIC示例文档/访问授权。
- [x] 文档含tenant、doc_id、version、title、source、valid_from/until、withdrawn、段落；确定性chunk_id与内容摘要。新版本取代当前版本；同版本不同内容拒绝覆盖；撤回/再摄取不能悄悄恢复，旧版本不返回。摄取原子提交，失败不留下半套可检索数据。
- [x] 查询参数只含问题/top_k/策略/模拟时点，身份从入口注入；同租户允许的本地演示用户才可查询，其他用户/租户不读到内容。有效期[start,end)，撤回优先；无匹配/低相似度返回unknown，不能批准。
- [x] 引用包含文档/版本/chunk/原文摘录/源摘要/有效期；返回抽取式证据回答，恶意制度文本只作为带标签的原始数据，不执行指令或改变权限。

## 3. 检索与评测

- [x] 简单精确向量top-k与向量+中文词项重合的混合重排比较；固定开发问题/支持片段标注，单独报告recall@k/MRR与引用支持，保留无改善/退化。
- [x] 测试先红后绿：切分稳定、版本冲突/替换/撤回、租户/用户隔离、时间过滤、无结果、引用原文、恶意文本不改权限；真实PG与真实本地编码分别标注，单元替身不当真实模型。
- [x] CLI摄取/查询/撤回支持可复现演示，权限从本地入口来，不建立通用后台。查询只读；摄取/撤回仅本地合成库，不涉及真实业务制度。
- [x] 独立审查、原有回归、结果与局限、状态/能力矩阵/学习/handoff更新后进入WP04知识工具整合，再接追踪与P2 Gate。该包默认不新增供应商请求，项目账本仍从6/100续算。

来源：上游[pgvector Windows与安装方法](https://github.com/pgvector/pgvector#installation)、[社区PG17发布](https://github.com/andreiramani/pgvector_pgsql_windows/releases/tag/0.8.6_17)、[FastEmbed模型清单](https://qdrant.github.io/fastembed/examples/Supported_Models/)。社区资产`vector.v0.8.6-pg17.zip`169689 bytes，GitHub发布元数据摘要`420388e9e9f05d92f06d6967ce8772483629b27a66ca9255925fa0fdd445438e`。
