# 安全生产评测基线 v2：合同回归首包

三个 SYNTHETIC、开发者已见场景：资质不等于批准、材料缺地点追问、知识缺当前权威记录。来源为旧 runner-v1 的实际 JSON 字节，使用 SHA256、版本 pointer、原文 pointer 追溯。仅取合同必要字段，没有复制旧分数，也没有重新认证其中占位的 DOCX 摘要。

这不是企业金标、未见评测集或安全生产质量验收。所有标签为 AI provisional；human_review=pending，sealed_holdouts=[]。available_at、业务有效期是场景作者声明的合成固定条件；即使源文件字节被验证，也不认证现场时效或真实文控记录。缺地点的判断来自题面，引用的资质记录仅界定已提供事实，不能把该引用存在当作逐主张语义已验证。

从仓库根执行（输出必须不存在）：

```powershell
uv run --no-sync python scripts/validate_enterprise_eval_dataset.py --catalog evals/enterprise-eval-v2/scenarios-v2/catalog.json --output <new-manifest.json>
```

exit 0 仅表示数据合同、来源完整性与声明条件通过，模型质量仍 not_evaluated。exit 2 表示无效或输出已存在。入口不请求网络、模型、PG或业务工作流。

输出 `anlan-dataset-manifest-v2.0` 是独立的输入索引：catalog_sha256 和 case_sha256 使用严格解析后的规范 JSON（UTF-8、sort_keys、紧凑分隔符）；source_sha256 是源文件原始字节。后续适配器可按 case_id 回读 catalog 并核对摘要，建立 E1 Manifest/CaseResult，但旧 E1 runner 当前不直接消费此格式。不得将数据校验的 valid=true 填作 E1 semantic/human/safety pass。

版本变化应创建新数据版本并同步合同；不能静默覆盖已冻结或已运行产物。封存登记只接受指纹、family、文档摘要和生命周期，不接受题面、答案、标注或任意额外字段。指纹是防泄漏启发式摘要，不是加密保密机制；真实留出资料须在受控私有库保管，公开目录不能用它储存真实保密元数据。
