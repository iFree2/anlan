# 上游联网核验与许可边界

2026-11-22；浏览工具与本机无凭据HTTP读取分别记录。没有报告或语料全文落盘，未申请账户/填写组织资料/绕过访问条件/运行数据集脚本。许可缺失采用metadata_only，不由AI作法律授权结论。

|来源|本次核验|版本/许可/访问结论|
|---|---|---|
|[应急管理部2019目录](https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/2019tbzdsgcc/)|官网直接链接至[响水事故报告页](https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/2019tbzdsgcc/201911/t20191115_340720.shtml)，发布日期2019-11-15|公开读取；未见明确再分发许可，不能将“政府公开”当全文入库授权。固定URL但无不可变版本，全文hash为null。|
|[报告页当前附件](https://www.mem.gov.cn/gk/sgcc/tbzdsgdcbg/2019tbzdsgcc/201911/W020240229376281346471.pdf)|浏览器成功打开65页，署国务院事故调查组，2019年11月|附件URL含2024日期，而报告为2019；不以URL/发布时间冒充版本。仅核验元数据，不复制全文，也不把报告建议当现行法规。|
|[BAAI发布方卡](https://huggingface.co/datasets/BAAI/IndustryCorpus2/blob/main/README.md)|页面许可标识Apache-2.0，含extra_gated_prompt及Company/Organization、Country额外字段；含消防安全/食品安全及石油化工分类|README最新commit链接为[249ea52f1ee412303e9741ae69fdd2109c0f8e1c](https://huggingface.co/datasets/BAAI/IndustryCorpus2/commit/249ea52f1ee412303e9741ae69fdd2109c0f8e1c)。该链接与raw入口本次401；本机HF请求ConnectError。只锁定观察到的卡片提交，不宣称锁定所有子集。卡片声明不等于逐记录再分发权或专门安全生产题库授权。|
|[ModelScope BAAI/IndustryCorpus2](https://modelscope.cn/datasets/BAAI/IndustryCorpus2)|浏览工具页面无可读正文，本机200 HTML壳|发现入口；未取得独立版本/许可/下载条件证据，不下载库，不执行SDK或附带脚本。|

## 原字节观察与失败保留

原字节hash仅针对HTTP响应，不是正文或PDF hash，也不是许可证据本身。没有将网页原文存入仓库。`report-page-observation.json`记录本机报告页200、7803 bytes、响应SHA256及UTC观察时间；这是权威URL可访问的有限证据，不验证报告字节或永久可用性。

本机无重定向、20秒timeout、1MiB读取上限的首次元数据探测还得到：

- 旧候选目录index_1.shtml：200、8952 bytes，响应SHA256 `77c8b595a1ca403467a47e3e9629832a93a84b75f4e6877617a3452d53db53e1`；浏览工具抽取结果与搜索索引不一致，因此以2019目录→报告页直接链接为最终定位。
- ModelScope HTML：200、10561 bytes，响应SHA256 `381cdc6e046242239641a6074eb76d789d9d435dc403fb224d22d5186a6abe60`。此hash不表示数据集内容、许可或版本已验证。
- 曾试探错误报告页尾号340321，返回405；它不是实际报告页，后已通过官方目录找到340720，错误响应不作为报告证据。
- HF API和HTML本机ConnectError；浏览工具成功读取卡片却无法访问raw/commit。两通道结果分开，不推断精确故障根因或当前账户门禁。

真实网络证据不参与pytest通过率。离线合成回放不会升级本表未知项，下一包须取得许可依据及原文件hash后再考虑受限真实样本。此次没有真实全文样本，符合许可不明确时仅保存元数据的授权边界。
