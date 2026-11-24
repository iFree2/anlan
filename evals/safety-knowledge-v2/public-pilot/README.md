# 公开语料候选 v1

清单版本2026-11-23.2；全部candidate、not_enterprise_authority。本目录仅含来源元数据和一条已见SYNTHETIC合成文本，不含事故报告或数据集全文，不是专家金标或未见留出集。真实来源未进入任何检索或工作流。

sample.txt由本项目为本次离线边界测试新作，使用CC0-1.0声明：在法律允许范围内放弃该合成样本的版权与相关权利。该声明仅覆盖sample.txt，不覆盖应急管理部、BAAI、ModelScope的任何内容。合成样本及许可证据统一使用`synthetic://public-pilot/sample.txt`，由`access=offline_fixture`、`content_kind=synthetic_case`、`data_origin=project_fixture`共同标识。合同拒绝合成样本使用HTTPS地址，也拒绝真实来源使用synthetic URI或混用标志。后续真实数据导入需实际宿主回执与许可审核。

```powershell
uv run --no-sync python scripts/curate_public_safety_corpus.py validate evals/safety-knowledge-v2/public-pilot/manifest.json
uv run --no-sync python scripts/curate_public_safety_corpus.py replay evals/safety-knowledge-v2/public-pilot/manifest.json --source-id synthetic-pilot-v1 --file sample.txt
```

replay使用清单同目录内普通文件；CLI只验证离线字节，因此HTTP字段取固定本地回放值，不是网络访问证据。API replay可验证宿主提供的实际回执字段。不会写文件、下载、执行脚本或创建已发布文档；成功只说明合同/hash一致。输入目录须由可信宿主管理，路径校验不提供抵御本机恶意并发文件替换的OS沙箱。

真实报告使用前先核定全文使用权限、稳定文件hash与人工领域审核；事故案例不是法规/现行企业依据，数据卡的汇总许可不自动证明各记录来源权利。证据见docs/phases/engineering-20261122-public-corpus/upstream-evidence.md。
