# 安全生产评测基线 v2：场景与标注首包设计

日期：2026-11-22。按任务 C 授权，设计自审后在本窗口继续 TDD，不提交、不 SSH、不部署。

## 设计门禁与选择

已核对根约定、status、architecture、最终交接、P9 plan/acceptance、E1/E2 与知识评测设计/报告、evaluation 源码和已见场景。E1 Manifest 不允许额外字段；旧 runner 只接受固定脚本目录。因此采用独立 dataset 包与严格 dataset manifest，后续运行器显式适配，首包不修改 E1。另两种选择是扩展旧合同（破坏冻结与所有权）或直接把旧分数转金标（无人工证据），均不采用。

场景合同固定 schema/dataset/rubric 版本，所有嵌套模型 extra=forbid。每例有 ID、family、业务切片、严重度、固定时点、明确合成来源、输入、必须风险、允许未知、必须追问、禁止主张/动作、必要事实/知识证据、答案范围及九项独立阻断项。必要字段不能省略；允许无风险/无追问的空列表，阻断项必须全集。

来源按仓库相对路径、真实字节 SHA256、原文 JSON pointer、可得时点与逻辑文档/版本标识记录。证据引用必须解析到真实原文；当前证据须在固定时点有效，未来可得数据拒绝。只读取传入仓库根内的 JSON，不执行路径、网络、模型或业务工具。不将合成 IR 中占位的 DOCX 摘要当真实原文件摘要。

## 防泄漏与生命周期

公开 cases 只允许 seen_regression，开发者已经看过的所有合成例永不升级为未见。sealed_holdouts 仅为不含题面/答案/标注的严格元数据登记，首包为空，不制造真正未见数据。记录 family、源文档版本摘要和封存时间；发现 family、同源逻辑文档（即使换版本）、原文摘要或规范化近重复跨分区即拒绝。近重复采用 NFKC/大小写/去标点、数字归一化和字符三元组 64 位 SimHash，跨分区汉明距离不超过 3 即拒绝；这是避免登记原题文本的保守启发式，无法证明语义无泄漏。公开回归目录中相同规范化指纹也拒绝，防止仅改 ID/数字扩充样本。

封存记录不可携带题面/答案，曝光只能转 exposed 并记录 exposed_at；之后 retired，不能恢复 sealed。exposed/retired 均要求见过的对应 case ID，保持回归归属；此历史链只验证所提供记录的一致性，不认证外部保管人未隐瞒曝光。

## 临时标签和人工工作流

provisional_label 明确 AI/人工草稿来源、rubric、逐主张 rationale 与 evidence IDs，不等同真人审核。human_review 独立，保留 pending/disputed/approved、reviewer_kind、reviewer_id、signed_at、signature_ref、所签 case digest。首包没有真人认证基础设施：任何已签/approved 记录均 fail closed，不能靠 reviewer_kind=human 字符串冒充真人。pending 不能夹带签字。AI 临时标签可以存在，真人字段保持空。争议有独立 ID、主张、双方意见、状态和处置；未决争议不能批准。后续真实审核必须另接可信签字验证与不可变审计，不能直接删掉本门禁。

## 输出与失败

validator 先严格 parse，再核对引用/摘要/时效/分区/标注，返回结构化路径和错误码，不回显答案。CLI exit 0=数据合同有效（不代表质量通过），2=无效，输出独占创建。manifest 固定版本、catalog SHA256、case 内容摘要、source 摘要、family/split、human=pending、quality=not_evaluated、model_requests=0；不输出题面、答案或 holdout 答案。现有 E1 不直接读取此新格式，必须后续显式转换。

## 自审结论

所有产物限任务 C 所有权；无共享接口变更、无 SQL/部署、无企业金标/真实未见/真人签字声明。真来源引用与自报语义证据区别明确；签字认证缺口采取拒绝而非接受虚假身份。当前证据时效不能由被标注答案覆盖。版本变更须新目录/新标识，不能覆盖历史。

## 实施小计划

1. tests/test_enterprise_eval_dataset.py 先写正例及重复 ID、跨 split family、近重复、时间/版本、证据缺失/篡改、阻断项缺失、AI 冒名、holdout 泄题、extra、CLI 独占输出的失败测试；运行并保留 RED。
2. src/anlan/evaluation/dataset/{contracts,validation,manifest}.py 与 __init__.py 实现严格模型、纯验证和无答案 manifest；scripts/validate_enterprise_eval_dataset.py 提供离线入口。
3. evals/enterprise-eval-v2/scenarios-v2/ 建立三个去重的已见 SYNTHETIC 合同回归示例，引用既有事实和知识 JSON 实际字节，不复制旧评分结果。
4. 定向 GREEN、恶意输入自审补测、E1/E2/知识相邻回归、Ruff、diff check；在 report.md 记录命令、结果、限制及仅撤自有文件回滚。
