# P13 B3 提前审查记录（未验收）

2026-10-28。实施会话 `01a17e1e-d39c-7360-a59f-bb6ccc19f646`，基线eaad71e/4393072（仅进度文档差异）。当前是未提交实现的提前只读审查；以下问题均已交回原会话。尚未取得最终提交/交接/独立复验，不以此文件表示B3通过。

## Important：private legacy事件兼容

初版ConsoleService.simulate/review无条件要求P13可信绑定。真正private legacy任务无协作行，不能经BindingService建立绑定，原ConsoleProfile事件路径因而恒409。要求先真实旧路径RED，再仅对持久化协作/P13任务强制绑定；private legacy维持原profile范围与私有权限。新协作任务缺绑定不得回退profile；旧已完成协作也不能当private legacy。

已向原会话发送修复要求，最终源码/RED-GREEN待复核。

## Important：旧共享事件缺binding_revision

初版_current/process_event对source.binding_revision=None跳过对象绑定检查。旧P12共享receipt/review升级后没有该字段；申请换人/换区域但材料版本不变时，旧核查仍可能current，反馈也沿用此判定。要求补“旧shared None→升级/换绑定”真实PG覆盖，标历史未绑定或stale_binding，保留只读记录和原报警active。只有真正private legacy兼容None；stale_material等原语义需保持。

已向原会话发送修复要求，最终源码/RED-GREEN待复核。

## Important：生成确认卡片前的人工选择竞态

初版HumanCitationCandidateRequest仅会话revision/结论/引用IDs，adapter.freeze从最新shared填入check/material/binding/application版本。用户勾选A批后，候选提交前后台产生B批；若chunk IDs相同、会话revision未变，旧选择可被静默冻结为B并确认。

要求专用人工选择请求携带、持久化并原样冻结用户所见expected_check_id、expected_material_revision、expected_binding_revision、expected_application_version及会话revision；服务端一致性检查失败返回409，不替换最新版。UI发送实际显示快照，模型候选仍不能代选引用。需覆盖“勾选后/生成卡片前变化”，而不只“卡片生成后变化”。

协调实际核对route/request metadata/freeze后确认，已交原会话。最终源码/RED-GREEN待复核。

## 执行纪律

审查者只读，没有运行测试、改代码、SSH或模型调用。协调不并行改B3源码，原dirty与私密配置保留。B1/B2已验收；B3三项关闭并完成接口/UI/事件/浏览器交接后再做独立验收，B4仍未启动。
