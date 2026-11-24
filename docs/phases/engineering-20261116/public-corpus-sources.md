# 公开语料候选登记（2026-11-16）

用户在工程推进中提出：语料可否从 ModelScope 等公开网站取得。可以作为候选来源；本登记只记录已查来源和用途，不代表已经下载、取得全文再分发授权、审核发布或形成领域金标。

| 来源 | 查证结果 | 安澜用途与边界 |
|---|---|---|
| [ModelScope BAAI/IndustryCorpus2](https://modelscope.cn/datasets/BAAI/IndustryCorpus2) | 平台搜索有行业语料卡片，含消防/食品安全行业分类；页面动态内容未取得可读全文 | 作为候选发现入口；不是专门动火/化工安全金标库，不盲目下载全库 |
| [BAAI 发布方数据卡](https://huggingface.co/datasets/BAAI/IndustryCorpus2/blob/main/README.md?code=true) | 发布方卡片标注 apache-2.0，包含额外访问条件字段 | 后续固定 revision、子集、许可副本与原始来源；按业务筛选、去重、追溯与审核，不把预训练语料当现行制度 |
| [应急管理部事故调查报告目录](https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/index_1.shtml) | 官方目录可查响水化工、天津港等报告 | 事故案例/原因/措施与背景引用；不是全部企业适用的操作规定，不替代当前事实；逐份检查附件与来源定位 |
| [ModelScope 数据集下载文档](https://modelscope.cn/docs/datasets/download) | 官方入口存在，动态页面无可读正文 | 实施下载时以锁定版本 SDK 官方文档为准，不执行数据集附带任意脚本 |

## 接入门禁

每份原文件或记录登记 publisher/source_url/retrieved_at/upstream_revision/license/license_evidence/hash/content_kind/validity/review_state。缺许可依据、来源不可追溯或内容存在争议时保留 candidate，不能自动 published。只在本地暂存，仓库优先保存清单、许可和可再分发合成夹具，不提交不明授权全文。

法规制度优先原始发布机关与效力核验；事故报告定位为案例；开源问答作为临时开发题，公开已见题不作为未见留出。不使用通用大模型“内容安全”题库替代安全生产领域评测。专家审核仍需真人记录，AI 不能代填。

公开来源可补知识和开发资料，不能提供本企业当前人员资质、设备状态、进场授权、作业票与厂区编号映射；这些仍须可信企业服务或明确 SYNTHETIC 替身。
