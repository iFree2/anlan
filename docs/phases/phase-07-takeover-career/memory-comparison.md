# 两枚举偏好：现有PG实现与Mem0 OSS有限比较

核对日期2026-10-05。选择Mem0；Letta未安装/未比较。本轮只下载官方源码作静态阅读，没有导入、安装或执行Mem0，没有框架延迟/质量/成本实验。固定commit为`abb81c88e1f738a8117d8293530fbc31a5ef8fd9`；三个文件URL、SHA、关键行及本地能力见[evidence](evidence/wp02/framework-source.json)。

官方[快速入门](https://docs.mem0.ai/open-source/python-quickstart)默认LLM/embedding使用OpenAI，配套Qdrant与SQLite；[配置文档](https://docs.mem0.ai/open-source/configuration)支持替换组件，但组件自托管不意味着所有调用留在本地。本项目授权只有既定DeepSeek有界请求，不能直接运行默认示例。

固定[main.py](https://github.com/mem0ai/mem0/blob/abb81c88e1f738a8117d8293530fbc31a5ef8fd9/mem0/memory/main.py)的882—904行可见infer=False仍执行embedding；构造器还装配LLM。该路径不等于无外部调用。核对的add/search/update入口未见本项目expected_revision或candidate/confirm状态机；这仅是所读接口的合同差异，不能据此推断整个框架完全不支持冲突管理。[telemetry.py](https://github.com/mem0ai/mem0/blob/abb81c88e1f738a8117d8293530fbc31a5ef8fd9/mem0/memory/telemetry.py)默认启用遥测；将来集成前需在导入前显式禁用并实际核验。

| 对比问题 | 本项目基线（实际验证） | Mem0（静态观察，未实测） | 取舍 |
|---|---|---|---|
| 保存什么 | detail_level/presentation_order两枚举，仅呈现偏好 | 面向消息/自由文本记忆提取、搜索、更新 | 当前小范围无需泛化文本提取 |
| 来源/确认 | 版本反馈+宿主SHA，candidate显式confirm | metadata可承载来源；未证明等价人工确认边界 | 若集成，确认权与来源校验仍归宿主 |
| 身份 | tenant/user同时校验，候选/审计不跨用户 | add接user/agent/run，search用filters | user_id标签不是本项目服务认证；需宿主绑定复合作用域 |
| 冲突/修正 | expected_revision、conflicted、版本水位 | 未验证同样的并发版本/禁止旧来源复活合同 | 保留原PG权威，不双写两个当前值库 |
| 过期/删除 | 时钟读取即隐藏过期，tombstone与不可变历史 | 可见expiration_date和删除/历史入口 | 生命周期粒度与隐私语义需另测，不宣称相等 |
| 调用/预算 | 当前枚举操作零LLM/embedding | 默认LLM与embedding；infer=False仍embed | 若将来用，应给所有适配器接唯一预占/超时/无重试；本轮无此集成 |

结论是当前范围继续使用现有PG实现，不是Mem0性能或质量较差。没有同输入双框架实测，不报告胜率/提质/省token。后续只有自由文本记忆需求和可测收益明确后，才值得添加最小适配器；本包没有部署第二平台。

## 实际运行的基线与小任务

```powershell
scripts/dev-postgres.ps1 -Action Env
$reuseDir = '.runtime/reuse-' + [guid]::NewGuid().ToString('N')
.venv/Scripts/python.exe evals/evaluate_reuse.py --output-dir $reuseDir
```

[reuse-v1/report.json](evidence/wp02/reuse-v1/report.json)是一个合成受限空间资料任务：缺方式→补齐→新服务会话读取；跨tenant材料与工具拒绝。事实只有焊接记录，查询`synthetic_confined_training`返回unknown/not_applicable，不能推断具有或不具有现实资质；区域合成记录restricted。呈现偏好sources_first不删除未知。

同一真实PG实验保存偏好七个版本：candidate→active→conflicted→candidate→active→expired→deleted；新会话读取一致、另一个用户为空、旧revision修改被拒绝、未执行expire前过期读取已为空。全部反馈由合成脚本产生，不是用户选择或本人练习。预算42→42。

可复用的是通用四字段材料补充/版本/隔离、事实来源合同和两枚举偏好生命周期。未复用动火SYSTEM、动火知识/规则、感知事件候选合同；`context/assembly.py`的SYSTEM仍有动火语义，不能简单更名拿来做受限空间判断。输出只列观察、未知和未核实领域输入；没有批准字段、阈值、实际进入条件评估或第二业务系统。行业规则有效性本轮未验证。
