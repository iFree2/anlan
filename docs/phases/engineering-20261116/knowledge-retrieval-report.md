# K3a 本地受治理结构证据检索独占报告

日期：2026-11-17（设计与任务启动于2026-11-16，执行跨日）。状态：实现、定向验证和独立复审完成，K3a代码冻结；主窗口负责后续集成Gate。范围仅K3a，不表示K3全部完成或真实检索质量通过。

## 设计门禁与交付边界

主窗口D条件通过后才编码，原设计knowledge-retrieval-design.md保留并追加触发记录。三项D约束落实：每一路provider前重新读当前权威并重建可见CandidateText；CellLocation只从审核矩形IR推导（derived_from_reviewed_ir），不证明真实XLSX地址；64KiB按完整packet的UTF8字节测量，表元数据/源表与rows联动，裁必要依赖标incomplete。

只新增retrieval包、新前缀测试和合成夹具；未改K1/K2a、旧knowledge contracts/store/tool/embeddings、旧query_knowledge、T1核心、SQL或评测。未stage/commit、切分支或新建聊天窗口；原工作树并发改动保留。

## 文件和精确接口

- retrieval/contracts.py：严格冻结的TrustedRetrievalRequest、SearchParams、ClauseParams、TableParams、EvidenceKey、EvidenceItem、EvidencePacket v2、表格行/派生cell和固定issues/audit。模型可填Params不接收身份/权限字段。
- retrieval/catalog.py：InMemoryCatalog，完整IR验证/摘要、重复拒绝，32文档/8192块/8MiB固定上限，固定目录revision。
- retrieval/providers.py：GovernanceSource、BlockResolver、RankProvider、Clock协议；InMemoryBlockResolver和确定性离线排名替身。没有默认允许的权威源或真实embedding。
- retrieval/ranking.py：本地cjk-bigram-asciiword-v1 BM25、参数k1=1.5/b=.75；候选返回验证与k=60 RRF。
- retrieval/tables.py：最多200行、受限Decimal筛选，XLSX矩形尺寸匹配后推导地址，原始字符串、单位与未知值保留。
- retrieval/service.py：KnowledgeRetrievalService.search/get_clause/query_table，异步只读Python方法；请求局部授权与预算、每provider前后/投影前后/最终重检、父依赖闭包、64KiB与最终deadline。
- tests/test_knowledge_v2_retrieval.py、_security.py、_ranking.py、_tables.py：共88项K3a已见合成回归。
- examples/synthetic/knowledge-v2/retrieval/README.md、table-ir.json：手工合成结构表与边界。TXT场景由测试调用K2a从实际合成bytes生成IR。
- 本报告和knowledge-retrieval-design.md为本包docs输出。

constructor按已冻结合同新增可选host-only lexical参数，支持替换BM25与逐路spy验收。源文/定位/hash/IR摘要/发布代次/处理版本/请求及业务时点/最终核权时间/修订号均由宿主重新组装，provider只返回key/score。未装配旧工具、HTTP、CLI、T1或模型目录。

## 实际RED/GREEN和命令结果

| 组 | 命令或实际观察 | 结果 |
| --- | --- | --- |
| 合同RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_retrieval.py` | exit1；3 failed in0.24s，缺K3a包的明确断言 |
| 合同GREEN | 同上 | exit0；3 passed in0.15s |
| 目录/首链RED | 同文件扩充后运行，--tb=line | exit1；5 failed,3 passed in0.28s，缺catalog/service |
| 安全组RED | `uv run --no-sync pytest -q tests/test_knowledge_v2_retrieval_security.py --tb=no` | exit1；16 failed in0.31s，缺首链实现 |
| 首链GREEN | retrieval.py与_security.py | exit0；24 passed in0.88s |
| ranking/tables RED/GREEN（独占worker） | 两个对应测试文件 | 42 failed→42 passed；嵌套伪造key追加RED1 failed(TypeError)→固定合同错误后48 passed in0.39s，四文件Ruff通过 |
| 表格/预算集成RED | retrieval.py与_security.py | exit1；2 failed,29 passed in1.49s；缺预算计数元数据与非表格定位状态误为incomplete |
| 集成GREEN | K3a四测试文件 | exit0；79 passed in1.05s |
| 逐provider旧缓存回归探针RED | 独立临时Python进程仅monkeypatch _Run.visible复用首轮语料，再调用真实withdraw安全测试 | exit1 AssertionError；vector.spy实际收到已撤权A，证明测试检查输入而非只看最终packet；未改磁盘源码，进程退出恢复 |
| 预算/取消/恢复追加GREEN | K3a四测试文件 | exit0；82 passed in1.10s |
| 最终deadline及撤权issue RED | `...pytest -q tests/test_knowledge_v2_retrieval_security.py -k 'final_assembly or revoked_parent_issue' --tb=short` | exit1；5 failed,23 deselected in0.77s；组装/序列化超过5秒仍返回item，撤权后issues保留key均实际复现 |
| 上述修正GREEN | 相同定向命令 | 5 passed；随后K3a四文件87 passed in1.25s |
| 仅issue文档泄漏RED | `...pytest -q tests/test_knowledge_v2_retrieval_security.py -k issue_only --tb=short` | exit1；1 failed,28 deselected in0.43s；A仅缺投影issue、解析B期间撤回A，A未被最终重检 |
| 仅issue文档修正GREEN | issue_only/revoked_parent_issue/final_assembly联合 | exit0；6 passed,23 deselected in0.42s |
| 撤权audit脱敏RED/GREEN | revoked_parent_issue三种withdraw/acl/release | 3 failed in0.39s→6项联合passed in0.22s |
| 超时包audit脱敏RED/GREEN | final_assembly两个packet/serialize阶段 | 2 failed in0.69s→2 passed in0.61s |
| 最终K1/K2a/K3a定向 | `uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py tests/test_knowledge_v2_parsing.py tests/test_knowledge_v2_retrieval.py tests/test_knowledge_v2_retrieval_security.py tests/test_knowledge_v2_retrieval_ranking.py tests/test_knowledge_v2_retrieval_tables.py` | exit0；**218 passed in2.06s**，130既有+88新增 |
| 最终Ruff | `uv run --no-sync ruff check src/anlan/knowledge/retrieval tests/test_knowledge_v2_retrieval*.py` | exit0；**All checks passed** |
| 旧知识兼容 | `uv run --no-sync pytest -q -rs tests/test_knowledge.py tests/test_knowledge_tool_loop.py tests/test_knowledge_cli.py tests/test_knowledge_evaluation.py` | exit0；**11 passed,6 skipped in2.43s**，6项为既有缺ANLAN_TEST_DATABASE_URL的PG fixture，未改skip，不计通过 |
| 合成表夹具 | 用当前DocumentIR.model_validate_json读取table-ir.json并断言SYNTHETIC/unverified/A1:B4 | exit0；synthetic table IR valid；没有读真实工作簿 |

Ruff过程中自有代码的import/长行已修复，最终命令无错误。完整全仓回归由主窗口负责；不把主窗口此前1267项当本包最终集成结果。

## 独立审查important与修正

1. 主窗口审查：最终治理通过后packet构造/UTF8序列化/裁剪可能跨deadline。已实际RED/GREEN，在完整bounded_packet结束后最后monotonic检查；超时清items/rows与issue可定位key/audit digest，仅生成<=64KiB固定deadline_exceeded包，不启动新的权威/投影/provider任务。取消仍传播，不自动重试。
2. review_k1及主窗口复现：父投影缺失issue曾合法记录key，最终撤回时只删正文会遗留元数据。discard现在同时清同文档issue.related_key并去重、清audit.key_digest；整文档items/rows移除，K1依赖同文档所以不会留其他文档required_keys引用。
3. 同一important第二路径：文档只有key-bearing issue而无item，也纳入finish最终核权集合；预算/时间/权限失败统一discard脱敏。已有同请求invalidated集合不复活文档，已选release fingerprint变化不切源。

独立最终复审结论在下方追加；问题关闭前不宣称K3a审查完成。

## 验收事实与限制

每provider前后重新治理；lexical期间撤回/收权/发布变化后vector.spy不含该文档，全部失效则vector零调用。目录/IR回滚仍依赖独立最新ACL和撤回，不信任IR自带状态。跨tenant无provider输入、无可见ID/计数；scope缺失unknown，projection_missing/缺父依赖/预算不足incomplete；篡改IR摘要或投影完整块比较阻断。返回审计无正文/query/凭据，只含有界阶段/固定码/授权key摘要及整体预算计数；撤权/超时也清key摘要。

完整源文不按字符截断；64KiB按完整packet UTF8计算，删表item时同步删rows，删必要父块后子项dependency_state=incomplete。CellLocation标识derived_from_reviewed_ir，仅说明审核IR矩形尺寸推导；未重新打开XLSX、无真实物理地址正确性证明，source_text包含单元格字符串只证明转录包含，不能证明地址真实。

纯内存目录/投影，不是OpenSearch/PG持久化、索引生产发布或真实企业规模。向量仅协议与确定性排名替身，没有加载新模型/真实向量/检索效果或金标评测；旧512维BGE原样保留。编号仅显式文档/版本/代次/block_id，不自动解析法规条款。权限与依赖沿用K1整文档/同IR粒度，不伪造跨文档或块级ACL；complete只表示已声明结构组装，不是语义/安全完整。没有模型答案、自动批准、真实语料下载、法律/人工认证、云或部署。

治理源原子最新读取和发布认证由可信宿主负责，checked_at不能证明后端未重标旧记录；普通离线检查后的外部撤回竞态不能被此函数完全消除。消费者缓存/重排/使用前仍需当前治理，本包不提供缓存/授权令牌。provider是可信协作async代码，不能隔离阻塞事件循环/恶意Python。异常映射固定码、不复制异常文本；直接构造Pydantic ValidationError可能含输入，未来外部入口必须脱敏。TXT/表来源均合成已见夹具，不冒充真人签字或真实来源授权。

## 回滚

只移除本包新增retrieval/、test_knowledge_v2_retrieval*.py和retrieval合成夹具及自有报告/设计追加。未装配旧链、不需SQL回滚；不得reset/clean共享树、删除共享工程报告目录或回滚权威ACL/撤回账本。全部旧源文件与并发窗口文件保留。零live模型、零平台安装、零云操作。

## 独立最终复审与冻结交接

主窗口integration_review实际运行 **88 passed**、定向 **10 passed**，限定Ruff通过；主窗口协调复验也为88 passed。复审明确 **无剩余Critical/Important**，已确认最终deadline、撤权issue/audit脱敏、issue-only文档最终重检、表格裁剪联动。主窗口指令冻结K3文件，不扩新包；后续E1三场景集成若需API支持由主窗口协调。

本窗口最终本地证据为218项知识v2定向通过（130既有+88本包）、限定Ruff通过、旧知识11通过/6既有缺DSN跳过；没有把skip算通过，没有运行真实模型或全仓PG Gate。报告及合成夹具已保存，源码和测试保持当前稳定检查点，不作接口变更。
