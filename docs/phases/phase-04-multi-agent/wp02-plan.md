# P4-WP02：风险候选、证据复核与受限协调

2026-09-21。基线fb3eef2，WP01已验251测试/9行三路工具对照/4命令CLI。依持续授权继续同目录实现，不等待常规确认。沿用brainstorming、writing-plans、TDD、只读审查与验证技能。

## 设计

选择固定两步模型协作：risk用现有context-v2生成ReviewCandidate；evidence reviewer仅获实际已入risk上下文的观察/知识、宿主分配claim_id的候选、问题与材料版本标识，不获偏好、历史或执行能力。不同提示与独立上下文构成职责分离，不宣称独立模型供应商、多数投票或自治团队。比单模型多一次请求，可明确测成本/退化。暂不采用无限讨论/动态路由或第三个协调模型。

复核输出每条claim的supported/unsupported/uncertain、简短理由和观察/原文来源，完整未知清单。宿主校验claim覆盖、不重复/伪造引用、未知保留与上下文字节上限；supported至少有来源，存在引用仍不证明语义。确定性协调不改写候选，只汇总需人工复核、存在异议、复核不可用；不把supported解释为批准。risk候选结构失败时保留拒绝候选、不请求reviewer。来源冲突/过期/工具错误保留，不用Memory替代。

可信入口固定P4-WP02：DeepSeekReviewModel新增可验证work_package参数，默认P3-WP03保证旧入口不变；多角色入口只接P4-WP02网关，不接受材料传包号。父级最多2个模型step、45秒，独立parent/child run_id；所有真实attempt仍进唯一PG账本，失败/取消/未知不退款。用户外部取消传播且清理，显式取消/超时返回已有候选与观察并停止下一步。最终材料复查只由宿主完成，不给模型/子分支Graph连接。

## 实施顺序

- [x] `tests/test_multi_review.py`：P4包号HTTP前预占、独立复核上下文、错误claim/引用/未知、受限协调、候选拒绝、父步骤预算、部分失败/deadline/取消/保留attempt；红测归档。
- [x] `review.py`只增加可信包号兼容参数，新增`multi_review.py`实现复核合同/上下文/网关、父级两步协调；不改P3输出合同和评分。
- [x] `multi_review_cli.py`新入口先授权任务再依赖/凭据，复用WP01采集；scripted与deepseek显式分开，最终材料变更标stale。
- [x] `evals/evaluate_multi_review.py`复用P3 review-v1同3任务/真实事实知识Memory，单模型1步 vs risk+review最多2步。同一材料、as-of、上下文与评分；最多9真实请求，不重试失败，不为漂亮结果补额外调用。
- [x] 先替身工程、真实PG与故障/HTTP协议测试，通过后读即时预算；既定deepseek-flash/端点、最多1024输出token/20秒单请求/无重试。子attempt使用父run可追溯列表；实验自身新增和其他新增分别核对。
- [x] 保留真实原始候选/复核、AI逐条复核及未改善数据；全量/ruff，更新status/矩阵/学习/handoff并提交；随后WP03少数Java API/MCP。

首包两例并行更慢、P3记忆无收益及材料引用合同缺口保持；个人掌握与模型泛化独立待验。真实实验是开发已见小样本，不是独立金标、Judge校准或生产业务决策。
