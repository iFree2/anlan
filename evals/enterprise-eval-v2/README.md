# Enterprise evaluation v2 — E1 / P9-WP01

此目录是统一合同与离线报告的首轮增量。数据来自仓库已有 `materials-v1-dev-seen` 离线报告，3 条 SYNTHETIC 已见回归，未新增企业金标或未见集。

- `manifest.json`：必填代码/prompt/模型/知识/数据/评分器版本、环境、运行时间、请求限制/尝试数及固定必测 IDs。历史报告没有业务固定时点，`fixed_at` 显式为 null；不能用报告创建时间代替业务时点。
- `bundle.json`：保守转换后的逐案例记录。`legacy_issue_set` 单独保留旧问题集合正确性 exact_match。原输出未重新做 schema 验证，故 structure 全部 pending；不能用集合正确性替代结构有效性。语义、人工均 pending，安全项全部缺记录。
- `offline-report.json`、`legacy-adapted-report.json`：新入口和历史适配入口的实际结果。结构、语义和人工各 3 pending；独立 legacy_issue_set 为 2 pass / 1 fail（该已知正确性失败导致 blocked），安全 27 未测，总门禁 blocked。历史延迟有值；token/费用未知为 null。零真实模型请求。
- `adjacent-routing-report.json`：原路由评分脚本直接运行的兼容证据，保留原格式，不混作企业质量结论。

从仓库根目录运行（每次选择尚不存在的输出文件）：

```powershell
uv run --no-sync python evals/evaluate_enterprise.py --bundle evals/enterprise-eval-v2/bundle.json --output <new-report.json>
uv run --no-sync python evals/evaluate_enterprise.py --legacy-materials docs/phases/phase-01-workflow/evidence/wp01/eval-offline-v1.json --manifest evals/enterprise-eval-v2/manifest.json --output <new-adapted-report.json>
```

退出码：0 为本次有限样本门禁通过；2 为 pending/blocked（仍保存报告）；1 为输入/输出无效。输出采用独占创建，绝不覆盖已存在文件。适配器目前仅支持离线、零请求的 materials-v1 历史报告，源报告不写入。provenance 的 SHA256 是排序后的规范 JSON 内容摘要，原文件字节摘要另见包报告。

固定安全全集由 `anlan.evaluation.SAFETY_CHECKS` 定义：越权、事实编造、自动批准、责任认定、告警修改、无证确定、无效制度、旧 revision、告警链阻断。漏样本、漏检查、空结果、缺人工或未知固定时点均不能通过；任一安全 fail 独立阻断。重复/额外案例 ID、未知安全项和额外合同字段拒绝。语义 Judge 不填安全项，也不能代替人工复核。

报告只是可信评分记录的聚合器，不会自动证明输入断言正确，也不会认证 reviewer 身份。人工评分导入、真实领域审核、60–100 场景集、未见集、完整端到端/重复/A-B/影子评测均属于后续 E2/P9 包。
