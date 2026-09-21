# P4-WP01 交接

2026-09-21。首包范围为受控确定性事实/知识分支，不是多模型自治。实现 `parallel.py`，现有review_cli增加 `--collection baseline|serial|parallel`，baseline默认不变；本包serial/parallel只允许scripted综合，不读取模型凭据。

计划与控制边界见[wp01-plan](wp01-plan.md)，失败、退化、真实PG/BGE三路同集9行、CLI4命令与测试见[验证报告](evidence/wp01/verification.md)。预算21→21，新增0；保持14文件原中文注释和.idea未提交。个人掌握仍待验。

继续WP02：独立风险候选与证据复核上下文、有限两步模型调用与确定性协调，保留主张冲突/未知/拒绝。先使DeepSeekReviewModel接受可信work_package且HTTP前验证P4-WP02预占；绝不占P3余下1次。再接父请求次数/期限/取消，子请求仍进唯一PG账本。真实对照用P3同三任务和评分，每任务单模型基线1次、多模型最多2次，总计划最多9次（包上限10），失败/拒绝不重试凑满。即时账本确认可用额度后才读凭据；模型语义结果与工程Gate分别报告。

P3材料说明缺引用类型、已接受候选错述上下文/离题引用、本人与AI证据区分继续保留。不要因多Agent复杂度升级而声称质量增加；WP01已有两例并行延迟退化。
