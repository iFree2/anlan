# Audit-only Model Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. 按用户明确“不设额度限制”要求在当前会话串行实施，保留原dirty路径，不开新批次/自动化。

**Goal:** 线上当前授权不设累计或分包调用次数上限，仍保留审计、单次执行保护和历史。

**Architecture:** SQL018新增按授权的limits_enforced策略，缺省true；显式false时reserve跳过两个次数检查但仍预占/finish。public_info用audit_only、null有效limit/remaining表达无限，不把原历史数值冒充现行上限。

**Tech Stack:** PostgreSQL/psycopg、Python/FastAPI、原生JS、现有固定host key SSH、wheel。

## Task 1：先测后改

文件：新增tests/test_audit_only_budget.py和src/anlan/sql/018_model_call_policy.sql，修改infrastructure/budget.py、interfaces/service_models.py、console/assets/app.js。

- [x] RED：真实PG中BudgetLedger(total_limit=1,package_limit=1)，reserve/finish一条后第二次拒绝。`INSERT INTO anlan_v2.model_call_policies(authorization_id,limits_enforced,reason) VALUES (%s,false,%s)` 后同包并发12条仍全部独立记账；前记录不变，initialize与新连接不重置策略。默认另一授权仍拒绝第二次。
- [x] RED：public_info使用实际审计ledger，无供应商请求；开启策略后budget.status为audit_only，total_limit/package_limit/package_remaining皆null，对话分包亦同，used真实可见。
- [x] `.venv/Scripts/python.exe -m pytest -q tests/test_audit_only_budget.py` 应因无策略表失败，而非无PG环境。
- [x] 新SQL018只建策略表/登记迁移，不自动关闭任何授权。BudgetLedger.initialize在_authorization前运行018；_authorization增加策略读取并缺省true，reserve两个比较只在limits_enforced时执行；保留预占与finish。snapshot返回limits_enforced和旧历史配置。
- [x] public_info按flag渲染audit_only与null有效上限；有限模式原输出保持。前端模式显示“项目调用次数不限（保留记录）”。不改最大单次请求、重试、token、work_package归属或现有消息。
- [x] 运行新测试和test_budget、test_release_budget、test_console_live、test_conversation_model、test_package_layout；真实PG、非live，Ruff通过。构建wheel，资源及离源码导入/四进程恢复验证；代码审查。

## Task 2：部署与验证

文件：deploy/aliyun/release_audit_only.py、当前P12部署说明和无凭据证据，ignored运维素材。

- [x] pinned SSH只读核对当前p12-demo-tokens、累计100和策略未启用，无pending；0700/0600备份DB/配置/发布路径与旧行摘要，校验新wheel。
- [x] 准备新目录/依赖与维护前向恢复，停服务后再次核对无pending，执行SQL018，仅给当前AUTH写false策略及用户要求reason，再切换新版。不清账/不改变旧授权数值。
- [x] GET info验证两个角色audit_only/null限额与真实计数，原任务草稿和未确认命令保持；125+新SQL实际文件匹配，旧行摘要及根站点保持。只读SQL证明当前策略和计数，不执行ledger.reserve/真实模型探针，不代用户提交材料。
- [x] 遇故障进入维护模式，不恢复旧DB/账本；forward只指向支持新策略的新版本，记录恢复命令。最终提交自有代码/文档，保留所有原dirty内容，交付无限项目次数、仍有供应商限制、0付费验证边界。
