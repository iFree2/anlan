# 「调研行业 Agent 案例」会话续接摘要

> 生成时间：2026-10-29
> 原会话：`01a159f1-0847-7f82-9080-01c8a66c295e`（创建于 2026-10-20，共 88 轮用户消息）
> 原会话元数据：`provider=openai`，最后一次线程设置 `model=deepseek-flash provider=openai`
> 用途：把这份文件粘到新的 DeepSeek 会话开头，即可接着干活。

## 一、为什么原会话打不开

原会话在创建时就把 provider 钉成了 `openai`（rollout 里 `session_meta.provider=openai`）。
现在 Codex 切成 DeepSeek 模式（`auth_mode=apikey`，没有 OpenAI 密钥），该线程每次发请求仍走
`api.openai.com/v1/responses`，因此稳定报 401。这是线程级绑定，不是配置残留，改配置无法迁移。

## 二、项目背景与目标

安澜（Anlan）2.0：个人学习用的安全生产领域 Agent。核心场景是**动火作业**，要求从
"传统表单 + 后端接口"改造成**对话式窗口**：识别用户意图 → 触发对应工作流 → 双角色协作。

已确立的核心业务主线：

```
作业前：申请人描述作业对象/方式/位置
     → 确认作业人员与作业区域
     → 提交申请
     → 自动预核查（人员资质 / 区域状态 / 适用规程知识）
     → 安全人员查看依据、补充或换绑定、重查
     → 人工完成材料核查
作业中：消费告警事件 → 结合已有核查依据分析 → 通知安全人员复核
```

关键设计判断（已确认，勿回退）：

- 资质、区域、规程的**首次查询必须放在作业前**，不能等告警事件后。
- "查询成功"≠"通过"：必须区分资质有效、区域受限、知识依据缺失。
- 存在缺口/异常/过时依据时**不允许完成材料核查**，但允许继续补充、换绑定、重提。
- 作业中再查资质属于**复核**语义，不是首次核查。
- 材料核查完成 ≠ 正式审批 ≠ 开工授权，演示脚本不得暗示。

## 三、已完成

- 对话窗口 + 任务侧栏 + 二次确认 + 受控路由器架构。
- 双角色独立会话，共享同一份作业申请。
- 部署到阿里云并可通过 `http://47.93.218.52/anlan/console` 访问（凭据不写入本文件）。
- 取消调用配额限制（不再受 100 次/30 次/10 次限制），历史记录保留。
- 演示脚本：`docs/demos/2026-10-26-hot-work-three-stage-walkthrough.md`（12 步操作、话术、预期结果、排障）。
- P13「作业前证据预核查」设计与验收清单：
  - 设计：`docs/superpowers/specs/2026-10-26-preflight-evidence-design.md`
  - 验收：`docs/phases/phase-13-preflight/acceptance.md`
- B1/B2 服务层已验收（G1 对象关联与授权、G2 自动预核查与完成门控多为已勾选）。

## 四、当前止步点

验收清单里未完成的是 **G3（双角色交互与事件复核）** 与 **G4（工程、兼容与交付）**。
正在进行的是 P13 第三批（UI）：已修「异常申请选定资质异常人员和受限区域」的目录加载、
依据时间与业务状态展示、完成入口，待验证：

1. 安全人员视角能否正确看到缺口；
2. 通过「补充 / 换绑定 / 重提」闭环处理缺口；
3. 完成后重新核对状态与依据引用是否正确。

最近提交记录：`docs: clarify pending P13 review checklist`、`docs: track preflight projection and cached evidence review`、`docs: track P13 UI review issues before acceptance`。

## 五、下一步建议

1. 打开 `docs/phases/phase-13-preflight/acceptance.md`，按 G3 逐条跑浏览器验证并勾选。
2. G4 按清单验证：TDD、本地 PG、并发/重启/Ruff、准确测试数与独立审查证据。
3. 通过后更新演示脚本与线上部署，再补作业中事件复核那条支线。

## 六、给新会话的指令建议

> 这是安澜 2.0 的 P13 工作续接。请先读 `docs/phases/phase-13-preflight/acceptance.md` 和
> `docs/superpowers/specs/2026-10-26-preflight-evidence-design.md`，然后从 G3 双角色 UI 验证继续。
