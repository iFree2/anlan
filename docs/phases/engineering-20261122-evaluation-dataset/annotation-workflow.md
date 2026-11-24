# 临时标注、真人复核与争议流程

1. 作者先选定 family 和业务时点，保留来源原始字节摘要、文档版本 pointer、原文 pointer。填写风险、未知、追问、禁止项、证据需求和九项阻断。已看过的资产全部 seen_regression，不因换 ID/改数字而变成新未见样本。
2. provisional_label 明确 author_kind=ai/human_draft，逐条填写 claim、rationale、evidence_ids。源文本可定位只证明引用存在；领域判断仍待人审。输入事实与制度依据不能互相替代，不得把没有记录写成事实已不存在。
3. human_review 与草稿分离。本包统一 status=pending、其余身份/签字字段 null。AI 不得代填 reviewer_id、signed_at、signature_ref 或批准。即使填写 human 字符串，本校验器仍拒绝签字，不把自报角色认证为真人。
4. 复核中出现分歧，在 disputes 新增唯一 dispute_id、争议主张、至少两个意见，status=open、resolution=null；human_review 改 disputed。不同观点和原草稿均保留，不取多数票自动结案。形成具体处理理由后才将 dispute 改 resolved、填写 resolution，人工签字仍 pending，不能以争议处理冒充正式审查。
5. 真实签字接入留待后包：必须从项目认可的独立身份渠道取得 reviewer 身份、领域资格、时间、所签 case/rubric/source 版本摘要和可验证签字/审批单引用。先建立可信验证器和不可变审计，再允许 approved；本包无导入“已批准”捷径，不生成任何虚假签字示例。
6. 真实未见数据由不参加当前调试者保管，冻结候选后另行运行。仓库仅登记 sealed 元数据。首次访问题面或答案即追加 exposed（严格递增时间、原因及匹配的回归 case），随后可 retired；无法重新 sealed。复核/训练/调试已经暴露的旧 holdout 只进入回归。

validator 只检查所交付目录与事件链的一致性。它不能证明保管者没有隐藏历史，不能认证人工资质、真实事件或来源可得时间；这三类证据必须在真实接入中补齐。修改历史事件仍可能形成另一条自洽链，必须由外部不可变保管审计解决。
