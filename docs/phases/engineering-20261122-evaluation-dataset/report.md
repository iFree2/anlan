# 任务 C：安全生产评测基线 v2 场景与标注首包

实施目录按 2026-11-22 任务归属保留；2026-11-23 续记。状态：实现及本地验证完成，独立审查结果见下文。无提交、SSH、部署或真实模型请求。

## 交付与边界

- `src/anlan/evaluation/dataset/`：严格 Catalog/Scenario/Source/Evidence/Claim/HumanReview/Dispute/Holdout 与独立 DatasetManifest；来源原始字节 SHA256、JSON pointer 引文与真实版本字段绑定；family/近重复/逻辑文档跨分区、时间、证据、九项阻断、人工身份和生命周期校验。
- `scripts/validate_enterprise_eval_dataset.py`：离线 CLI，0 表示数据合同有效，2 表示拒绝；输出以 x 模式独占创建，不覆盖已有文件，错误不打印输入值。
- `evals/enterprise-eval-v2/scenarios-v2/`：三个去重已见 SYNTHETIC 例（资质批准边界、缺地点追问、知识权威未知），临时 AI 标签，human 全 pending，封存登记为空。
- `annotation-workflow.md`：逐主张临时标注、人工身份与签字门禁、争议和 sealed→exposed→retired 操作规范。
- `validated-manifest.json`：实际 CLI 生成的严格无题面/答案 manifest；quality=not_evaluated、model_requests=0，供后续显式运行器适配。现有 E1 不直接消费这个新 schema，本包没有改 E1。

## 设计、TDD 与审查证据

先写 design.md、自审和小计划，再实施。初始命令：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_eval_dataset.py
```

初次 **22 failed in 3.24s**：dataset 包/CLI/目录尚未实现。实现后 **22 passed in 7.39s**，Ruff 同时指出一处长行，后已修正。

自审补攻击测试后运行：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_eval_dataset.py -k 'both_declared or exposure_must or relabelled'
```

实际 **3 failed, 24 deselected in 1.38s**，根因分别为：仅比较两份声明版本未回读真实源版本；曝光只验证 case ID 存在而未绑定 family/指纹/来源；未拒绝换 ID/数字重复题。修复为版本 pointer 回读、曝光强绑定、回归规范化指纹去重。随后 **27 passed in 6.92s**，Ruff All checks passed。

最终补充曝光后退休正例、争议状态与五类嵌套 extra 拒绝：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_eval_dataset.py
uv run --no-sync ruff check src/anlan/evaluation/dataset scripts/validate_enterprise_eval_dataset.py tests/test_enterprise_eval_dataset.py
```

实际 **33 passed in 7.38s**；**All checks passed!**。包括 socket.connect 哨兵、CLI 成功/坏输入/同路径输出不覆盖、不打印秘密值、签字伪装/来源与引文/分区攻击。测试不请求模型或业务系统。

独立只读审查发现两个 Important 和一个 Minor：未知字段名可在 schema error path 泄露秘密、expired 证据允许未来区间、数组 pointer 接受 00/负下标。先补测试，实际 **3 failed, 33 deselected in 1.13s**；再分别对未知键名脱敏为固定 `<extra>`、检查 expired.valid_until≤fixed_at、严格校验 RFC 数组下标与转义。随后 **36 passed in 6.79s**，Ruff 通过。独立闭环复核实际 **3 passed, 33 deselected**，确认三个发现均关闭，所审范围无剩余 Important/Critical；这不等于全系统安全认证。最终再补半开时间边界与 CLI 秘密字段名脱敏两项测试。

相邻回归（在最后六个纯测试补充前，源码已与当前相同）：

```powershell
uv run --no-sync pytest -q tests/test_enterprise_eval_dataset.py tests/test_enterprise_evaluation.py tests/test_enterprise_evaluation_runner.py tests/test_enterprise_knowledge_evaluation.py
```

实际 **120 passed in 84.64s**；无失败/跳过。该结果只覆盖这四份测试，不是整仓验证，也不是模型质量统计。

上述独立审查修复和全部新增测试后，以同一四份测试命令重新运行，最终 **131 passed in 89.67s**，exit0（其中本包 38 项）。最终限定 Ruff **All checks passed!**；77 份旧文件摘要仍 changed=[]；重新 build_manifest 与已保存 validated-manifest **完全一致**。没有将审查前 120 项结果作为修复后的最终证据。

实际 CLI：

```powershell
uv run --no-sync python scripts/validate_enterprise_eval_dataset.py --catalog evals/enterprise-eval-v2/scenarios-v2/catalog.json --output docs/phases/engineering-20261122-evaluation-dataset/validated-manifest.json
```

exit 0，valid=true、quality=not_evaluated、model_requests=0。文件内 catalog_sha256 是严格解析后规范 JSON 内容摘要，不是 catalog 文件原始字节摘要；source_sha256 才是来源原始字节摘要。

## 保留与限制

`protected-baseline.json` 在实现前记录既有 evaluation 顶层源码与 enterprise-eval-v2 所有旧文件，实际复核 **77 文件、changed=[]**。`git diff --check` exit0，仅有已有总文档 LF/CRLF 提示；本包不修改这些文件。工作区 HEAD 当次读取为 `ae235009d729a58969d560ee375a872d2c13e210`，它不包含本包未提交文件，不能称为本包源码提交。

`owned-files.json` 保存本包 8 份源码/测试/CLI/场景与 README 的实际原始字节 SHA256，排除 Python 缓存。catalog 文件原始 SHA256 为 `beab49993f85a089c7e8485fe101d0e582b9152a490a96cdfe3626a05c185aea`，与 manifest 内规范内容摘要区别保存。文档和 baseline 另在本目录保留，不冒称已签名制品或已发布版本。

本包不认证真实现场时效、来源可得时间、文控权威、领域资质或人工签字。人工 approved/任何签字一律拒绝，正式身份与不可变审计须后包接入；因此交付的是可审核草稿/争议流程，不是已完成企业金标。来源/指纹仅检查给定目录和声明条件的一致性；SimHash 为启发式（数字归一化，跨分区汉明距离≤3），可能误报或漏报，不证明语义无泄漏。封存历史不是外部不可篡改日志，不能证明保管者未隐藏曝光。真实留出不得把题面、答案或机密元数据放入公开目录。

必要事实与知识引用只证明可定位和版本/声明时点一致，不证明自由文本推理成立。未知和撤回等状态是场景输入条件，不因此成为真实知识治理的权威记录；合成 IR 的占位 DOCX 摘要没有被认证。三个样本不能代表 60—100 领域审核基线或 P9 全阶段完成，临时标签不得直接转成 E1 语义/人工/安全 pass。

## 回滚

无迁移、业务状态、预算账本、角色或线上改动。保留证据后，仅撤本任务新增 `src/anlan/evaluation/dataset/**`、`tests/test_enterprise_eval_dataset.py`、`scripts/validate_enterprise_eval_dataset.py`、`evals/enterprise-eval-v2/scenarios-v2/**` 和本独占文档目录；撤前复核后续编辑。禁止删除整个 evaluation/evals/shared 文档目录，禁止 reset/clean/restore、整体 stage、切分支或回退他人文件。统一发布由总窗口处理。
