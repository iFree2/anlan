# P12 B3 协调验收

日期：2026-10-24（Asia/Shanghai）。实现 `4726f27eda00d4236fc14ab42228c50655e20751`，交接 `cdf742d`。审查基线a12151f；中间1ea5130仅为协调README变更。B3实施会话现已idle完成，后续批次可串行接入。

## 独立回归

使用本地独立PG `anlan_p12_b3_20261023`，先运行dev-postgres Start/Env，将两个本地项目DSN指向该库，未打印DSN、未连接云端。协调实际执行：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_collaboration_conversation.py tests/test_collaboration_events.py tests/test_collaboration_console.py tests/test_conversation_model.py
.venv/Scripts/python.exe -m ruff check src tests scripts deploy/aliyun
```

结果：**59 passed in144.81s，0 skipped**，Ruff `All checks passed!`。覆盖本人会话、四类冻结卡片、撤权/参与关系丢失后的旧结果重放、申请人语义追问、角色模型上下文、事件真实actor/授权/currentness、轮询和迟到响应/草稿/换号等关键路径。

协调另读取实施会话最终JUnit：`final-verified.xml` 为202 tests、0 failures/errors/skipped；`final-ui-events.xml` 为15 tests、0 failures/errors/skipped。对应控制台记录202 passed in407.65s和15 passed in40.15s。它们与协调59项属于不同且重叠的运行，不相加冒充一次276项或完整全仓Gate。

## 只读复核

审查者对最终提交复核，无Critical/Important。原两项Important均已修复：

1. 缓存重放不再按当前role是否为空跳过鉴权；active_task_id、投影、协作application、pending和business_messages中的资源引用均重新经过当前材料访问边界。合法legacy本人私有任务保持兼容。
2. 申请人在同一授权任务锁/checkpoint读取中使用安全材料投影，保留具体issue_questions及checked/offline_not_checked/failed，再合并协作元数据；安全人员继续共享白名单，不能读取申请人私有分析/执行信息。

只读2秒等待仅针对读取，不重试模型或写命令；最终轮询/会话选择保护、核查currentness刷新、legacy目标任务不可用回执的兼容修改未发现新增权限或隐私阻塞。审查者未运行测试，测试证明由前述独立运行提供。

## 已知Minor与下一批

一项恢复健壮性Minor交B4必做：`CollaborationConversationAdapter._read` 在registry+draft已创建、首次reserve前崩溃窗口读到空checkpoint时，会因直接_project/索引status产生KeyError/500。应在B4先写真实恢复RED，再像原WorkflowService.get一样受控抛InvalidTransition/待恢复冲突，保持原task的显式恢复能力。它不造成越权，但**不能带着该项未关闭进入B5发布**，已加入G4验收。

B3自检确实使用两个Identity、两个conversation_id、同task到review_completed/version5/material revision2，原报警active；这些是开发自检，不代替B4独立双浏览器/真实进程重启/wheel Gate。自检知识库显式Unavailable，未知项如实保留，不能声称该次知识命中。

提交路径仅包含本批源码/测试/脚本与交接；原用户dirty路径仍为roadmap/status的P10段落、P10目录、tool_loop_live和.superpowers，未恢复或夹带提交。没有SSH、部署、真实模型调用或预算变更。

**结论：B3按本批范围通过，直接进入B4，不需用户重复确认。** P12整体、云端替换和双角色视频仍未完成。
