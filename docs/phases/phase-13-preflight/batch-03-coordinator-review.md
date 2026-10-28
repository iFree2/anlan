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

## Important：binding直接投影的当前对象授权

接入同锁precheck_projection后，初版在当前facts ACL校验前向view写入完整binding；校验仅在有job时执行，拒绝后binding仍在。无job或对象ACL撤销时，BindingService.get拒绝的对象ID仍可由协作GET/会话快照返回。要求任何对象投影前验证当前ACL；失败只返回安全状态，不带binding/原始证据。源码已加入binding_visible方向修复，最终真实PG红绿待核对。

## Important：旧会话缓存的对象与知识权限

新增证据进入会话snapshot后，finish_message缓存包含binding/facts/引用；原validate_cached只核task参与权。对象ACL/knowledge allowed_users撤销后，重放旧message request_id可能返回旧原文。

第一版补强只看fresh是否存在binding/evidence仍不足：A批权限撤销后，新B批有效，fresh非空不能证明A仍获授权。要求校验A自身权限或批次不一致时受控拒绝/安全重建，补“A撤权＋B有效→重放A”的真实PG覆盖；不重执行旧业务或工具/模型。源码已加入binding revision/check ID一致性拒绝方向，最终红绿仍待核对。

## 当前待交付

截至协调本次记录，B3尚未提交实现/handoff，test_preflight_console.py及两独立浏览器主线证据仍待完成。已在原会话继续完整B3，不能把局部Ruff或单条修复回复当作交付。以上前三项源码方向经审查确认，尚需最终提交/完整回归后逐项闭环。

## 执行纪律

审查者只读，没有运行测试、改代码、SSH或模型调用。协调不并行改B3源码，原dirty与私密配置保留。B1/B2已验收；B3五项关闭并完成接口/UI/事件/浏览器交接后再做独立验收，B4仍未启动。
