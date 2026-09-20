# WP03 交接：三例真实联调已完成

2026-09-20。用户要求AI继续开发、先自己跑通代码，先列各阶段掌握清单，个人练习不阻塞推进。roadmap已加入P1—P7的掌握重点与最小实践方向；个人证据仍在learning-log和capability-matrix独立记录。

真实请求：用户指定docs/DS.txt（Git忽略，仅当前进程只读使用）。3次DeepSeek请求、无重试、输入1126/输出58/总1184 token；三例已见合成开发样本最终问题集合符合标注。TP2分别来自1条规则和1条模型；不能称作模型泛化准确率100%。实际扣费未知、未查账户。3次额度已经使用完，不追加调用或覆盖结果。

原始证据：[报告与逐例复核](evidence/wp03/final-report.md)，同目录live/offline JSON及trace、pytest.xml。最终50项全部通过（含11项真实PG），ruff通过；独立复核通过。Prompt仍materials-v1、数据仍materials-v1-dev-seen，未调整标签或Prompt挑选结果。

实现修正：evals/evaluate.py向WorkflowService透传mode，避免真实评测状态误标offline；新增configuration/Prompt摘要/summary，失败与未知usage保留，缺密钥不留空报告。关联测试在tests/test_evaluation.py。另处理PG未启动时pytest回溯显示连接参数的风险：默认短回溯，fixture离开except后输出固定失败消息，tests/test_test_output.py覆盖连接失败与畸形DSN的stdout/stderr/XML；本地开发库密码已轮换，新终端重新加载Env即可。DeepSeek密钥未输出。

运行：`uv run pytest tests/test_model.py tests/test_evaluation.py tests/test_test_output.py -q` 无需真实模型；完整测试先 `scripts/dev-postgres.ps1 -Action Start`（或确认已启动后Env），再`uv run pytest -q`。阅读真实结果无需再次调用模型。

Git保护：冷启动发现14个文件的既有中文注释/文档字符串改动和.idea，保留；本包仅改相关评测/测试/配置/文档，不回退用户注释。代码目录不再扩展数据库基础设施。

剩余：P1阶段冻结评测/收尾Gate尚未完成，不自动进入P2。建议下一包围绕固定阶段回归集、剩余工程演示及阶段handoff；如需新真实样本实验，再明确调用边界。本人对类型边界、Graph、状态/恢复、规则与模型贡献等仍待验证，不能将本包AI实现和测试记为本人掌握。
