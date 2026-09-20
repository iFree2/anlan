# P2-WP02：有界模型工具循环与共享调用账本

2026-09-20，基于6842f0f；按用户长期授权连续实施，无需常规再确认。

**Goal:** 模型可选择WP01两个只读工具、观察结果并停止，非法动作/参数被拒绝，循环与真实请求都有可靠上限。

**Architecture:** 保留独立任务快照与证据包。新增模型动作DTO及受控循环，不修改P1材料Graph；身份只在宿主执行工具时注入。真实HTTP前通过项目PG唯一账本预占一次请求，完成后记录状态和可知用量。替身不占真实额度且显式标注。

**Tech Stack:** 已有httpx/Pydantic/asyncio/psycopg，沿用deepseek-flash、非思考模式，无自动重试；无新增依赖。

## 1. PostgreSQL累计账本

文件：`src/anlan/budget.py`、`src/anlan/sql/002_model_budget.sql`、`tests/test_budget.py`。独立工作者负责，其他文件由主代理负责。

- [x] 搜索现有账本后只建一个生产授权记录`20260920-long-term-v1`，授权说明引用status；每包10、累计100均为保守执行上限，P1历史单列。
- [x] `BudgetLedger(dsn, authorization_id=AUTHORIZATION_ID, total_limit=100, package_limit=10)`；`initialize()`幂等安装表与授权，同ID不同上限拒绝；`reserve(work_package, run_id)->attempt_id`持久化预占后才返回；`finish(attempt_id, status, usage=None, error=None)`仅记录脱敏状态与用量；`snapshot()`提供跨任务可核对汇总与逐次记录。
- [x] 事务锁住授权行后计数和插入，所有reserved/成功/失败都消耗额度；并发和跨连接不能超限；硬退出保留reserved，不推断请求未发出并退款。不提供自动重置、删除或重用额度接口。
- [x] 测试独立授权ID/更低测试上限，不消耗生产授权额度；验证并发、重连、失败与未知预占、重复finish不覆盖、上限不漂移；PG错误不输出DSN。

## 2. HTTP动作协议与受控循环

文件：`src/anlan/tool_model.py`、`src/anlan/tool_loop.py`、`tests/test_tool_model.py`、`tests/test_tool_loop.py`。主代理TDD实施。

- [x] 模型请求只发送合成四字段、明确引用、当前工具观察和白名单Schema，不发送tenant/user/凭据/隐藏推理。请求JSON总量上限32KiB，max_tokens=1024、单次20秒、默认每次核验最多3个模型回合与4次工具动作。
- [x] 模型响应仅接受assistant合法tool_calls或stop；工具函数名白名单、call_id唯一、参数JSON可解析且符合WP01 DTO；拒绝非法动作，保留可解释观察，不执行未授权工具。
- [x] 工具观察作为role=tool附带原call_id；代码决定预算与停止，不允许模型改写身份/状态。工具结果和最终摘要独立呈现，模型文本标为未验证候选，不能当合成事实或批准。
- [x] 正常停止、非法/重复call_id、非法参数、超步数、工具额度、模型/工具超时、错误和无依据提前停止均留证；失败不丢已有工具结果。
- [x] HTTP替身检查协议、预占先于发送、失败占用、输出长度/结构和用量。取消/超时保留已预占记录，不隐式重试。真实预算账本不可用时不发请求。

## 3. CLI、实验、评测与交接

- [x] CLI `check-facts-agent`复用任务归属校验；默认scripted替身可离线演示，显式deepseek使用PG共享账本；预算查询入口只读展示当前生产汇总。
- [x] P1模型入口若继续保留真实调用能力，也必须接共享账本，不能利用旧3次进程上限绕过项目额度；旧材料真实功能只在明确实验中运行，不重跑P1样本。
- [x] 准备少量版本化合成工具任务与确定性工程评测，分别评估动作/参数/停止和事实支持，开发暴露如实记录。
- [x] 在账本与HTTP替身通过后，用现有指定凭据路径只读加载到进程，运行最多3个真实合成任务，每任务最多3次请求，总计不超过本包10次。所有请求先占额，失败保留，不为追求通过无限重跑。
- [x] 独立规格/代码审查、必要PG集成/P1回归，更新status/矩阵/学习/handoff，随后自动进入示例知识检索工作包。

官方依据（2026-09-20核对）：[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。按工具Schema发送、按tool_call_id反馈观察；应用仍需自行校验模型参数。模型只输出候选，权限与停止由代码负责。

边界：不扩供应商/模型价位；无业务写操作、RAG、多Agent或生产认证。PG账本是应用级防重复超额保障，不代替供应商账单或独立账户限额；有数据库管理权限者仍可篡改，需如实声明。
