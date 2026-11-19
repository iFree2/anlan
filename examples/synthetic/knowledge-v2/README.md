# K1 合成合同样本

`document.json` 是人工构造的已见回归数据，不是从 DOCX 解析所得。
`source_sha256` 和配置 hash 是格式合法的占位值，没有对应原文件；校验 hash
格式不证明源文件真实性。DOCX 只保存段落锚点，不伪造分页。

目前实现只包含 DocumentIR v2 校验与纯治理决策。PDF、DOCX、XLSX、文本、
图片的定位类型可表达来源，但真实文件解析、OCR、页预览、搜索引擎、文件
真实性校验、人工内容审核、发布持久化、索引切换和三类证据工具均未实现。
表格包含多级表头、行、单位和脚注；合并单元格及公式模型留待真实解析工作包。

治理调用只接收可信宿主输入。宿主必须为每次决策（包括缓存命中、父子扩展、
重排前）重新原子读取最新 ACL 和撤回账本，传入当前选定发布清单；这些输入
不能取自 IR、旧索引、旧缓存或模型参数。`checked_at` 是本次权威读取时点，
`effective_at` 是业务适用时点，后者不能用于回退授权。缺 ACL 或明确的撤回
记录会拒绝。离线纯函数不能检测宿主把旧记录重新标成当前时点的行为。

K1 适用范围使用可信任务的非空、完整精确标签集合；必须与发布清单相同，
且 ACL 覆盖全部标签。没有通配符、隐式继承或模型推断适用性的语义。
发布清单的 `ir_sha256` 绑定审核过的完整 IR（包括定位、血缘及检索文本），
治理函数重算 `DocumentIR.content_digest()` 并比对。规范化方式为已验证模型
包含默认字段的 JSON，键排序、UTF-8、非 ASCII 保留、紧凑分隔；该摘要
只证明与清单内容一致，不能认证原文件或发布者。宿主不能根据未审核的 IR
自动重写已审核清单的摘要。
`verify_quote` 仅证明该块给定定位下的连续转录文本匹配；不能证明转录正确、
定位真实或主张得到语义支持。

测试：`uv run --no-sync pytest -q tests/test_knowledge_v2_contracts.py tests/test_knowledge_v2_governance.py`。

## K2a 受限 TXT 候选摄取

新增 `anlan.knowledge.parsing.text.parse_txt`：仅接收可信宿主已经取得的
SYNTHETIC UTF-8 bytes 和无路径逻辑文件名；固定上限 256 KiB/4096物理行，
拒绝BOM、无效UTF-8、控制字符和非TXT后缀。模块不读取路径、不联网。

原字节保留于冻结草稿，实际计算hash；非空白行保留全部字符与换行，空白行
原始行号单独记录，不压缩后续定位。SourceCandidate中的来源/版本/许可未知
均可登记，但草稿始终needs_review且published=False，不自动创建发布清单。
直接构造草稿也会验证完整IR与同一raw的确定性拆行一致。

`ingest/sample.txt` 与 `ingest/candidate.json` 仅为明确合成样本，publisher、revision、
license未知，无真实来源认证或再分发授权证明。原字节持久化、真实路径读取
适配和其他格式尚未实现。测试：`uv run --no-sync pytest -q tests/test_knowledge_v2_parsing.py`。
