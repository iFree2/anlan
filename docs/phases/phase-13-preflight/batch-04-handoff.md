# P13 B4 本地 Gate 交接

日期：2026-10-29。基线 `f5921be`；本批只执行本地 SYNTHETIC 验证，不 SSH、不部署、不调用真实模型。

## 交付

- `scripts/verify_preflight_release.py`：P13 专用本地 wheel Gate，复用已审查的 loopback 目标锁定、四层进程/端口校验和受限临时目录清理。
- `tests/test_preflight_release.py`：配置、资源、远程目标拒绝和新输出文件边界。
- `test_collaboration_release.py` 的 wheel 重启用例已切换到 P13 Gate；原 P12 流程不再被当成新任务的当前绕过路径。
- 双角色可重复演练：`docs/demos/2026-10-29-preflight-dual-role-walkthrough.md`。
- 部署、备份、维护和前向恢复边界：`deployment.md`。

## 测试先行

1. 队列响应重放 RED：首次确认响应无 check/evidence，后台随后产生首批依据时被误判为撤权。
2. 修复后 GREEN；新增确定性命名为 `test_replay_of_queued_preflight_remains_idempotent_after_evidence_exists`。
3. P13 release 测试先因 Gate 文件缺失而 RED；实现配置/资源/目标拒绝后 6 passed。
4. 旧 P12 wheel 集成测试因新任务缺绑定而不能崩溃注入，已改为 P13 Gate；定向重跑通过。

## 最终验证

完整非 live 回归：

```text
1044 passed, 1 deselected, 1 warning in 793.98s
```

排除项为 `live_model`；未执行用户未授权/未提交的真实模型测试。唯一警告来自第三方 Starlette `BlockingPortal` 弃用提示。JUnit 为 `.runtime/p13-b4-full-final.xml`，0 failures、0 errors。

Ruff：

```text
python -m ruff check src tests scripts
All checks passed!
```

wheel：

- `.runtime/p13-b4-dist/anlan-0.1.0-py3-none-any.whl`
- SHA-256 `3155719ed37c44f958711a13471f47277e582b95891f4aa5e2425783b0d156cb`
- 资源清单包含 SQL019/020、Preflight 路由、Console 资源和全部 Python 模块。

P13 wheel Gate：

- 3 个不同实际 PID，cwd 在源码目录外，每代监听/退出/PID/模块来源均核对。
- 初始异常对象为 worker-alert + restricted area，结果显示资质 `suspended`、区域 `restricted`，不能完成。
- 换为正常对象后绑定 v2，重启进程后重提并得到当前知识引用。
- 再次重启后完成申请 v5；事件使用 area-normal 和 binding v2，核查 current，原始报警保持 active。
- 临时配置和进程已清理，未记录凭据；报告 `.runtime/p13-b4-gate-report.json`。

浏览器：

- 两个隔离上下文完成正常提交、异常缺口、要求补充、换绑定、重提、人工选引用和材料核查完成。
- 同一申请生成事件并核查；原始报警保持 active。
- 390×844 模拟视口 `scrollWidth == innerWidth == 390`，无横向溢出。
- 截图和结构化摘要见 `evidence/b3-browser-*` 与 `evidence/b4-p13-gate.json`。

## 兼容与限制

- 旧已完成协作申请保留历史并显示“未执行本版作业前预核查”；旧未完成申请按 required 升级。
- 私有 legacy 事件保持原 profile 路径；持久化协作任务缺绑定或换绑定后旧事件不能继续 current。
- 直接 HTTP、普通聊天、结构化卡片重放、旧 API/会话材料写入均经过或受制于同一完成门控；相关真实 PG 用例已纳入全回归。
- SQL019/020 为增量；017/018/012 与旧审计、角色令牌和 `audit_only` 预算策略未被改写。
- 固定业务时钟和公开合成语料只用于可重复验证，不代表真实法规、现场状态或企业平台。
- 本次未部署、未做真实模型泛化、未验证正式认证/TLS/SLA。
- 全量回归、Gate 和本轮自审已完成；**尚未取得独立代码审查者签字**，因此 G4 首项的“独立审查证据”保持未勾选。

## 保留的失败

- 首次 Gate 在就绪前超时；原因是克隆了含 118 个旧申请的测试库，启动升级遍历超时，不是业务通过。改用独立空库后通过。
- 第二次 Gate 因相对 embeddings cache 在离源码 cwd 不可用，知识返回 error；Gate 已将相对缓存锚定到源码工程 cache 后通过。
- 早期相邻回归的缓存重放 404 已修复并有确定性 RED/GREEN。
- 第一次全量回归 1043 passed / 1 failed；失败为继承 `PGPASSWORD` 触发目标保护，清除环境后定向重跑仍暴露旧 P12 Gate 不兼容 P13，已切换到新 Gate；最终全量通过。
