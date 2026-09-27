# P5职责入口

沿用ADR009的包边界，不另建框架或改历史R1映射。

| 职责 | 规范模块 |
|---|---|
| 事件合同/关联规则 | `workflows/event_contracts.py`、`workflows/events.py` |
| 感知合同/有界综合 | `workflows/perception_contracts.py`、`workflows/perception.py` |
| 感知模型协议 | `llm/perception.py`（固定P5-WP02，服务默认不启用真实模型） |
| 原始记录/来源水位 | `infrastructure/events.py`、SQL005 |
| 重核/反馈/持久取消 | `infrastructure/perception.py`、SQL007/008 |
| 显式材料修订/幂等创建 | `workflows/service.py`、`workflows/registry.py`、`infrastructure/postgres.py`与SQL006 |
| 关联/重核装配 | `interfaces/event_runtime.py`、`interfaces/perception_runtime.py` |
| 可信本地配置/HTTP/SSE | `interfaces/service_config.py`、`interfaces/api.py`、`interfaces/streams.py` |
| 启动与CLI | `interfaces/serve.py`、`interfaces/events_cli.py`、`interfaces/perception_cli.py`；原CLI新增revise |
| 工程回放/验真 | `evals/evaluate_events.py`、`evals/evaluate_perception.py`、`evals/phase05_gate.py` |
| 清洁启动/CI | `scripts/prepare_service_demo.py`、`scripts/smoke_service.py`、`scripts/ci.py` |

SQL/assets继续由`files('anlan')`读取。旧CLI薄转发仍保留；模块`__init__`不批量装配。材料锁、Registry与Saver仍为同一专用连接；原报警先单独提交。实际目录与wheel内容由验收报告的完整指纹核对。
