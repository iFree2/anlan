# P3-WP02：上下文工程已验，进入WP03

2026-09-21，首包提交dddd23d后同目录继续。纯组装器`context.py`按24000最大UTF-8序列化字节保留边界/材料/事实和未知，再装知识原文、有效枚举偏好、历史。必需部分超限抛ContextBudgetExceeded，不能丢未知后继续请求。每个可选项记录id/reason/item_bytes；模型token只从usage取得。身份、来源和权限来自宿主，所有正文是数据。

真实模型适配器新增可信构造参数work_package，历史默认保持，P3显式包号在HTTP替身发送前完成预占的测试通过；本包没有真实模型请求。后续综合入口固定P3-WP03，材料或反馈不能指定包号。

验证：[初步24项](evidence/wp02/green-initial.xml)，[相关回归82项](evidence/wp02/regression-recheck.xml)通过，含Memory与共享预算真实PG、原工具循环/知识引用；ruff通过。[8场景上下文消融](evidence/wp02/ablation.json)全部符合预期：无/有记忆1924/2159字节，去知识原文2016字节，过期/越权/无关/注入/删除偏好均剔除且保留expired未知。此为已见合成输入的组装行为，不是token、费用或模型质量收益。

失败原件保留：[模块/包号RED](evidence/wp02/red.xml)。第一次相关回归[regression.xml](evidence/wp02/regression.xml)为81通过1失败，原重复call_id测试返回loop_timeout，报告墙钟46682秒；[单项复跑](evidence/wp02/timeout-recheck.xml)和82项重跑通过。没有修改P2超时逻辑，疑似运行环境长暂停但根因未证实，不能宣称已修复。只读审查未发现其他实质缺陷。

下一步[WP03](wp03-plan.md)：版本化业务指引、真实三工具/PG单Agent综合入口、逐主张引用与未知覆盖验证，3任务×无记忆/有记忆/无知识原文对照；最多9次本包真实请求，先读即时预算账本。P2语义引用不足、混合无收益和PG退出原因未明继续保留；个人掌握不变。
