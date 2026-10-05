# 两张示意图的有限真实多模态对照

2026-10-05，最多4请求实际4请求，无重试/无追加调参。输入为离线合成资料，推理通过远程API，不是本地离线视觉模型。官方支持核对及不带尾斜杠URL初始超时记录见[official-support](evidence/wp03/official-support.json)。现有deepseek-flash及原端点支持图片，未换供应商/模型；官方映射V4.1-Flash，实际回应标识deepseek-flash，无法由别名证明历史权重完全一致。[官方Vision](https://api-docs.deepseek.com/guides/vision/)

[manifest与图片](../../../examples/synthetic/multimodal-v1/manifest.json)在请求前冻结，SHA为`51784269fc0a3d9bacaf4541e572c255fa2b2884c45e41dba778f7ba774edb6a`。两张几何图由程序绘制，不是真实视频/员工素材，也不是拿AI图像生成结果当识别证据。gold由AI按夹具构造，仅本地评分；真实响应和attempt_id在[live-v1.json](evidence/wp03/live-v1.json)。

| 输入 | schema有效 | 标签匹配 | 输入/输出/总token | 两次Gateway调用墙钟合计 |
|---|---:|---:|---:|---:|
| structured | 2/2 | 2/2 | 365/33/398 | 3618.48ms |
| image | 2/2 | 2/2 | 732/33/765 | 2621.23ms |

图1与对应结构化输入均为bare_head；遮挡图2均为not_visible；所有输出requires_human_review=true。图片多367token（约92.2%），本组无质量增益。两次调用墙钟包含PG预占/结算与API传输/生成，固定顺序structured→image且每格只有一次；不能据此声称图片更快。没有估算实际账单金额，token不是金额。

工程约束：每例每形式一次，输入约10KiB且不超过原32KiB上限；PNG内联user块，不用外部图片URL/上传服务。1024输出token/20秒/无重试，响应上限64KiB。新可信包P7-WP03只用于本次独立图示任务，没有调用P5感知候选或重置其包计数。入口发现本包已有任何预占即拒绝整轮重跑；此门槛在单一执行者约定下有效，不声称实现分布式实验锁。

17离线检查通过。请求前独立审查发现“换输出目录可重复一轮”缺口，repeat-red两失败复现，修正包已有预占即拒绝后repeat-green通过，再冻结preflight-final-v2才运行。没有重复付费实验覆盖原件。最终PG46/100：44succeeded、2原失败、0reserved，P7-WP03=4/10、P5-WP02仍4/10。新增1097输入/66输出/1163token；新授权累计71843输入/9910输出/81753，P1历史1184另列。

这仅说明既定API接受这两张示意图且返回正确有限标签。不能推导真实工地、真实头盔、遮挡/光照分布、视频时序、报警准确率或现场安全决定能力；没有helmet_present正例，也没有独立留出或统计泛化结论。模型失败与Q-P6-001/002均未因本次2/2而关闭，本人掌握仍待证据。
