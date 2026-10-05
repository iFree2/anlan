# P7-WP03：两张合成示意图与结构化输入有限对照

2026-10-05先核对[官方模型页](https://api-docs.deepseek.com/quick_start/pricing/)和[Vision](https://api-docs.deepseek.com/guides/vision/)、[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)。既定deepseek-flash当前对应V4.1-Flash且支持user图片块，仍使用原chat/completions端点。供应商模型别名映射会变化，不声称历史与现在权重完全相同。

问题：仅对两张512×384手工程序绘图识别“头部可见且无头盔”或“头部被遮挡无法判断”，与相同信息的结构化输入比较。不是实际视频、人脸、人员身份或作业现场识别；无真实员工素材/AI生成照片/联网搜图。第二例要求unknown，不能把看不见当没戴。标签为AI构造的显式夹具，不是独立人类金标。

固定2例×2输入形式（structured→image），最多4请求且每例每模式一次；顺序固定，不统计显著性。先冻结输入PNG/结构字段/gold/Prompt/runner SHA，模型输入不含gold或期望标签。结构化基线绕过图像理解，因此不属于等算力视觉模型竞赛。

实现`evals/evaluate_multimodal.py`，复用ModelGateway的32KiB输入/64KiB响应、20秒、1024输出token、固定供应商/模型/无重试和唯一PG预占。可信包常量P7-WP03只服务此独立图示实验；不追加P5感知候选复验、不调用PerceptionRuntime、不改变P5-WP02计数。两请求一组网关，总上限4，PG累计/包上限同时校验。异常保留attempt/部分输出/用量null，最终账本不可用保持总数未知和本轮已知下限。

输出严格有限枚举head_observation与requires_human_review=true；不含自由控制命令/批准。结构合法与逐例gold匹配分别记录，供应商返回的model标识单列。真实实验只有显式--live，默认只生成预检报告，无密钥读取；实际实验当进程读取已授权docs/DS.txt但不输出/保存密钥。

先红绿验证：图片/结构模式互斥、gold不泄露、输入摘要变更拒绝、非法/批准输出拒绝、PG预占先于HTTP、失败/最终快照异常不记零。再运行4请求，保存预检/失败/结果与token/模型阶段耗时，不重复刷分。学习/矩阵/handoff如实更新后进入WP04。
