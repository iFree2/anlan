# 任务A：公开安全生产语料候选首包报告

启动2026-11-22，完成复验2026-11-23（Asia/Shanghai）。仅独占新增文件，未stage/commit、未切分支/reset/clean、未SSH/部署、0真实模型请求。留给总协调窗口复验、集成和统一发布；未修改总文档及既有knowledge/retrieval/workflow/MCP模块。

## 交付

- `src/anlan/knowledge/sources/{__init__,contracts,validation}.py`：版本化不可变candidate清单、许可证据与精确URL校验；纯离线原字节回放，不下载、不发布。
- `scripts/curate_public_safety_corpus.py`：validate/replay，清单256KiB、样本64KiB上限，拒绝穿越/绝对路径/链接；只输出候选摘要，不复制全文或覆盖输出。
- `evals/safety-knowledge-v2/public-pilot/`：三项真实来源metadata_only及一条49 bytes已见SYNTHETIC夹具；SHA256精确绑定。真实报告/数据集全文均未入库。
- 本目录design/plan/upstream-evidence/report及JSON证据；`owned-files.json`列出自有文件与hash（不含自身）。

官方目录已追到响水报告页和当前PDF链接，报告不是法规；公开访问没有被当作再分发许可。BAAI数据卡有Apache-2.0声明及额外访问条件，但raw/commit本次401、本机HF连接失败，ModelScope仅HTML壳，均如实保留。锁定README可见提交不代表已锁定底层子集。详细URL、版本与访问差异见[上游证据](upstream-evidence.md)。报告页响应hash保存在[HTTP观察](report-page-observation.json)，并非报告PDF/正文hash；真实content_sha256均为null。

## 设计门禁、TDD与审查

按本任务授权，先写design.md并完成自审再进入小计划；不追加用户许可门禁。选择元数据+纯离线校验，未选择自动爬取或接生产RAG。最初测试收集因缺少sources模块失败（ModuleNotFoundError），之后37项GREEN；这是缺模块RED，不声称当时为业务断言失败。

追加许可证据空白2项断言RED（DID NOT RAISE）→约束修复GREEN。修复时发现URL预处理会剥除原始空白；1项清单级断言RED→两个URL字段改为before validator→扩展六项控制符回归GREEN。独立审查public_corpus_review也复现同问题P2；复验确认关闭，最终49 passed/9.84s，无未关闭Critical/Important。另覆盖空体积/NUL/denied许可及portable symlink模拟；不将模拟称Windows实际符号链接创建验收。

## 分层验证

|验证|结果|
|---|---|
|新增离线合同/恶意URL/许可/回执/hash/路径/CLI|本次62 passed、5.26s；独立复核62 passed、7.77s（含原49项）|
|新增+相邻contracts/governance/parsing/retrieval|本次连续203 passed、7.84s、exit0（含原190项）；JUnit `.runtime/public-corpus-20261122/synthetic-uri-continuous.xml`；原190/16.78s保留continuous-final.xml|
|同组上一轮|190 passed但报告耗时83048.50秒；保留`.runtime/public-corpus-20261122/final.xml`，不推断休眠/时钟变化根因，不作延迟指标|
|定向Ruff|All checks passed；早期import格式失败已修复|
|自有范围git diff --check|exit0；新增未跟踪文件另作内容/尾空格扫描|
|validate与replay CLI|4条candidate登记、合成回放candidate/hash/49 bytes一致；tmp cwd下运行成功|
|离线wheel|构建成功；本包3个Python文件逐字节匹配；离源码、临时目录、python -I导入并回放成功|

最终wheel SHA256 `7e040f7108ec93bef3e2c700fb37e8f6c99f2aaeef402dc80fb2f8f59ec37897`，位置`.runtime/public-corpus-20261122/synthetic-uri-dist/anlan-0.1.0-py3-none-any.whl`；详见[制品校验](package-check.json)。该wheel包含当时共享工作区其他代码，本报告只证明本包文件匹配及导入，不将它授权为集成发布制品。初轮wheel已被后续修复替代，不用于发布。

复现命令：

```powershell
uv run --no-sync pytest -q tests/test_public_safety_sources.py tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py tests/test_knowledge_v2_retrieval.py
uv run --no-sync ruff check src/anlan/knowledge/sources scripts/curate_public_safety_corpus.py tests/test_public_safety_sources.py
uv run --no-sync python scripts/curate_public_safety_corpus.py validate evals/safety-knowledge-v2/public-pilot/manifest.json
uv run --no-sync python scripts/curate_public_safety_corpus.py replay evals/safety-knowledge-v2/public-pilot/manifest.json --source-id synthetic-pilot-v1 --file sample.txt
```

## 限制与下一步

这是受限登记/回放工程，不是已接入真实企业知识、人工金标、未见集或模型质量提升证明；本人掌握不升级。许可字段为经宿主审核的证据声明，工具只能验证一致性，不能证明填写者具备合法授权。工具没有网络能力，因此URL白名单/redirect拒绝不被称作可抵御DNS rebinding的下载沙箱；未来网络下载需单独设计连接/DNS/超时与信任边界。

本地输入目录须可信，不防恶意本机并发替换文件；CLI的固定status/content-type只表示离线回放，不伪造网络证据。正文不作为指令执行、不接业务状态。后续需核定政府公开使用或逐记录许可，固定原文件hash/版本，真实小样本与专家审核后另开包；未获许可保持metadata_only。撤回仅由总窗口按owned-files核对后移除本包自有文件，无数据库迁移或业务数据回滚。

## 2026-11-23 总窗口审查修正：合成来源身份

总窗口指出合成记录使用政府HTTPS域名可能被误读为官方来源；原先note免责声明不足以建立机器可验证的来源隔离。清单更新为2026-11-23.2，新增required data_origin：真实来源为public_source，合成记录为project_fixture。合成source_url和license.evidence_url统一改为`synthetic://public-pilot/sample.txt`。只有access=offline_fixture、content_kind=synthetic_case、data_origin=project_fixture全部匹配才允许synthetic URI；合成记录不能使用任何HTTPS定位符，真实来源不能使用synthetic或混用fixture标志。

修复前新增合法synthetic回放测试观察RED：旧合同拒绝synthetic URI与data_origin字段，1 failed/13 passed；随后实现身份/URI联合校验，并验证两个URI字段、三个标志的部分组合、真实来源冒用synthetic及恶意synthetic语法。新增13项加原49项共62项GREEN。独立审查额外穷举八种标志组合，仅全匹配接受；默认validate_url仍拒绝synthetic；无未关闭Critical/Important。审查时读取的旧README文本已同步为新版本和URI。

本轮不请求网络，upstream-evidence.md与report-page-observation.json逐字节hash对比原owned-files清单保持不变；真实条目除新增data_origin外原元数据不变。sample.txt原49 bytes与内容SHA256保持不变；更新的是清单、合同/测试、README、设计及报告/制品/所有权hash。旧b20f29a…制品被本轮新wheel替代，不用于集成发布。新wheel自有3个Python文件逐字节匹配，python -I离源码导入/新清单synthetic回放通过；详细证据见package-check.json。仍未stage/commit/SSH/部署、0真实模型请求。
