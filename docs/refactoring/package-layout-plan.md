# R1职责分包与依赖收敛

2026-09-22。用户明确要求按经验分包，并由当前任务唯一写入；P4-WP03收束后优先本包，验收前不启动P5、不加无关业务功能、不请求模型。继续使用设计/计划、TDD、只读审查与验证技能；持续授权不等待常规设计确认。

## 结构选择

采用按职责与功能混合的浅层包，避免全部塞domain或机械Java三层。`interfaces`是CLI/HTTP/MCP入口与具体工作流装配；`workflows`是材料、采集与单/双角色协调；`llm`是供应商配置/网关/模型协议适配；`knowledge`、`memory`、`context`、`tools`保留各自合同与实现；`infrastructure`是数据库连接/持久化/预算/观测；`common`只放StrictModel/Identity/NonEmpty与通用访问/状态异常。每包有真实职责，__init__保持轻量。

先拆纯合同与连接边界，再迁移调用者；SQL/assets留包根且保持bytes，`files('anlan')`不变。运行入口保留anlan、python -m anlan及已公布的cli/memory_cli/review_cli/multi_review_cli/mcp_server薄转发；内部模块不做全量旧路径别名。测试monkeypatch、嵌入子进程代码、MCP子进程命令、eval/script与console entry同步使用规范模块。

关键依赖收敛：

- postgres的database_url/conninfo→infrastructure/db.py，不导入工作流；postgres_service→interfaces/runtime.py。Registry和Saver仍在同一专用连接，锁丢失阻断旧写。
- Identity/StrictModel/NonEmpty→common/models.py；共享访问/状态异常→common/errors.py且只有一个定义；材料字段/问题合同留workflows/material_contracts.py。
- AnalysisFailure→llm/contracts.py；供应商配置独立llm/config.py；KnowledgeCitation→knowledge/contracts.py，review不再因引用DTO加载tool model适配器。
- memory偏好常量/Feedback/MemoryConflict→memory/contracts.py；context只读纯合同，不为两个枚举加载PG。
- 模型综合适配器与脚本替身从review流程抽到llm/review_model.py；候选合同留workflows/review_contracts.py；采集/宿主校验仍在workflows。
- business_bridge拆tools/http_client.py与interfaces/fact_http.py；MCP客户端在tools/mcp.py、server在interfaces/mcp_server.py。Java源与scripts位置不动。

## 用户改动保护

搬迁前保存14文件完整worktree副本、git diff及每个英文→中文变更行与SHA，记录旧新路径映射。实际移动当前worktree内容，不用HEAD覆盖文件。最终提交时仅在Git index逆向隔离这些32行用户改动，工作树仍保留中文；不提交.idea。拆文件后逐行定位用户变更的新归属，数量/文本验证不变，并保留备份。历史原始evidence、冻结JSON与SQL/assets预先记录摘要，迁移后逐一核对，不重写历史报告哈希。

## 实施与验收

- [ ] WP03可运行基线：17Java/MCP故障测试、3真实PG/BGE整链及全量；保存实现提交与失败记录，P4阶段Gate保持待完成。
- [ ] 记录源模块依赖、用户改动与旧新路径；新增轻量导入/连接层/CLI转发/资源/wheel验收，先红测。
- [ ] 分批抽合同/连接与装配，再移动当前内容、批量更新代码导入和动态路径；不做大范围格式化。
- [ ] import/compile、monkeypatch与CLI、原任务PG恢复/丢锁、工具/MCP、Memory、知识、预算回归；ruff/uv锁/wheel离源导入/资源与入口验证。
- [ ] python -O P2/P3冻结回归、P4已有同任务工具与两角色替身、Java/MCP整链；新报告写R1证据目录，历史原始工件bytes不改。
- [ ] 独立只读审查、修复有证据的问题，核对用户32行新路径unstaged、更新status/architecture/ADR/交接、提供目录树/映射/真实结果，精准提交。
- [ ] 向协调任务回传提交与验收摘要，再恢复P4阶段Gate→P5原路线图。

兼容范围是既有命令与业务/数据合同，不承诺所有内部Python导入路径永久兼容。历史运行器文件保留路径但更新代码imports，新的runner_sha256按新运行真实记录，不修改旧报告中的摘要。既有活跃anlan chat不终止；被占用的Windows console可用旧薄入口继续，验证使用虚拟环境Python，构建在独立输出目录。
