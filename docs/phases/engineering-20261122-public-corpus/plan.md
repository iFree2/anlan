# 公开语料首包小计划

**Goal:** 只读候选清单、许可证据及安全离线回放。
**Architecture:** 独立Pydantic合同与纯校验函数，CLI只读取本地文件；不接旧RAG。
**Tech Stack:** Python3.13、Pydantic2、pytest、stdlib。

- [x] 在tests/test_public_safety_sources.py写清单、URL、回执/导入、CLI测试，运行`uv run --no-sync pytest -q tests/test_public_safety_sources.py`确认缺实现RED。
- [x] 新增sources/contracts.py与validation.py；严格字段、URL白名单、许可导入门禁、原字节SHA256及64KiB上限，运行同命令GREEN。
- [x] 新增scripts/curate_public_safety_corpus.py、evals/safety-knowledge-v2/public-pilot清单/合成夹具，validate/replay离线演示；真实来源证据独立记录。
- [x] 按requesting-code-review技能请求独立审查，只读本任务文件；问题先加RED再修复GREEN。
- [x] 定向+相邻知识回归、Ruff、diff check、隔离wheel导入校验；写report.md及所有权hash交总窗口，不commit/stage/SSH。
