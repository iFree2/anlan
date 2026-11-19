# E2a runner-v1：8 条真实离线已见场景

本目录是固定宿主可信输入根。场景全部为 SYNTHETIC / seen_regression，属于控制合同回归，不是企业金标或未见集。`cases.json` 不含任何预制评分；原生 API 的实际返回、异常、计数和状态/trace 观测才进入评分。

`facts/*.json` 从既有 `examples/synthetic/facts-v1` 复制，`document.json` 从 K1 SYNTHETIC DocumentIR 复制；`materials.json` 为明确标注合成的材料输入。原夹具不修改。K1 文档中的 source_sha256 是合成占位值，不表示已读取真实 DOCX。治理发布输入里的 approved / SYNTHETIC-policy-fixture 仅用于刺激策略，human 始终 pending。

运行（仓库根目录）：

```powershell
uv run --no-sync python evals/evaluate_enterprise.py --run-scenarios evals/enterprise-eval-v2/runner-v1/cases.json --artifacts-dir <new-local-output-root>
```

输出目录按 eval_run_id 独占创建，禁止放在本夹具根内。旧 --bundle / --legacy-materials 参数仍保留；新模式不接受 --output/--manifest。退出码：0 有限样本门禁通过；2 完整运行但门禁 pending/blocked；1 输入/输出/完整性异常。

8 场景包含：正常事实两工具、引用对象越界、跨租户拒绝、真实 reader 注入失败、不支持引用、K1 当前发布、历史时点查询被最新撤回拒绝、缺撤回权威记录拒绝。事实循环和 K1 各走当前真实原生 API；K1 尚未装配到旧知识工具循环，不能把这套运行器称为完整业务知识链验证。

每次运行保留 manifest、严格 run-index、逐案例 input/observation/trace、bundle/report。E1 Manifest 未扩字段，文件/prompt/lock/dirty/fixture 丰富版本信息只在 run-index。每个 Check.evidence 用结构化 JSON 引用对应观测文件、SHA256、case_run_id、JSON pointer 和评分规则。input_sha256 记录原始文件字节；input_content_sha256 记录规范 JSON 内容，用于跨换行格式的评分依赖验证。

`verify_run(index_path)` 校验全部文件摘要、case/run/manifest/input 绑定、原生 trace 的起止和治理决策、模型/工具事件及身份/版本/结果，然后从保存的 observation 重新评分并逐例完整比较 bundle，最后重新聚合 report。只对 bundle 重算 report/hash 不能掩盖工具失败或擅自填安全 pass。该检查不是对可信宿主恶意重写全部观测和所有摘要的密码学认证。

首份实际交付见相邻 `runner-results/123a7fc5-343f-48f6-9aad-629ed41f2138/`：8 例完整，verify valid=true，门禁 blocked（保留注入的 tool:data_error）。结构 7 pass / 1 pending（跨租户在入口拒绝，无原生结果）；语义/人工各 8 pending；安全 5 pass / 67 pending。正常场景未刺激旧 revision，stale_revision 保持 pending。费用/token 未测为 null；零 provider 请求单独记录。延迟为本地 case 装配/原生调用/输入与 trace 落盘、截止 observation 组装前的实测值，不包括评分/报告序列化，不能用来推断真实模型或生产链延迟。

每例只建立独立内存材料基线，然后验证核验前后 get/history 完全不变；不写持久化业务状态、不接 PG。trace 显式本地 exporter，忽略环境 OTLP 地址，不发 HTTP。运行器只读取本根内解析后的夹具路径，拒绝根外 catalog/path 和目录穿越；不根据任意 catalog.parent 自动授权。
