# P7-WP02：有限Memory比较与一个合成任务复用

目标：比较现有两键偏好生命周期与Mem0 OSS合同，实际复用通用PG材料/工具/偏好资产完成一个受限空间合成资料核对任务。

采用官方文档＋固定commit源码静态比较；本机Mem0/Letta未安装，默认Memory路径会涉及LLM、embedding及遥测配置；infer=False仍调用embed，不能直接接现授权账本。现有基线真实PG运行，框架不安装/导入/执行，无框架性能或质量胜负结论。相比默认安装框架，这个有限路径满足当前两枚举偏好问题，避免在没有收益证据时增加平台。

新建`evals/evaluate_reuse.py`和`examples/synthetic/confined-space-v1/`，固定单一合成任务：缺方式→补齐→跨会话读取；只读查询保留not_applicable/受限区域；偏好candidate→confirm→conflict→correct→confirm→过期读取→delete，验证跨用户/tenant隔离与旧revision拒绝。结构化移交包仅列来源、未知与人工待确认，不复用含动火SYSTEM的模型上下文/动火规则，不生成作业批准。

先写`tests/test_reuse.py`验证错域输入拒绝和未知保留；红绿后运行真实PG实验，失败/预算前后保存，新输出路径不可覆盖。记录素材/runner SHA、基线用量与框架未运行项。最后更新学习/矩阵/status/handoff/验收并单独提交。全包零模型调用，个人题不阻塞下一包。
