# P6-WP01验证记录

- 冷启动：HEAD bf65266，未发现适用AGENTS，保留16路径32行译文及用户学习排序/.idea；32项最小smoke通过，PG生产预算32。
- diagnostics-red.xml：8项中4失败，复现提示缺完整Schema、顶层/嵌套额外字段名泄漏、响应信封诊断缺失；另外4项确认已有JSON/Schema/应用引用与未知拒绝路径。
- diagnostics-green.xml：29项通过。integration.xml：21项真实PG/修订/CLI/评分集成通过。
- 独立只读审查发现外层HTTP解析先于感知parse，导致[]/null/坏JSON无诊断。outer-red.xml首版测试自身有过长参数ID造成路径错误，不计有效完整红测；outer-red-v2.xml为4项明确失败。失败工件保留。
- ci-v1.json：408 passed、0 skipped，锁文件/ruff通过；这是补外层诊断之前的源码快照，不作为最终版本全部验证。
- gateway-green.xml：补网关固定诊断标识和每次重置后，82项通过；含其他网关使用者及重复run不会继承旧诊断。独立审查复核43项离线测试通过，无新增问题。
- 真实复验见live-report.md：2次、2接受、5843token，生产预算34；旧2失败不改写。
- 最终ci-final.json：412 passed、0 skipped，锁文件/ruff通过，源码前后指纹一致；84项postgres标记真实PG。

历史P5 ImportError触发原因、P2 PG异常退出、P3长暂停超时未定根因均继续保留。本包不修订这些结论。尝试集成命令时一次文件名写成test_material_revision.py导致未收集测试，修正为仓库实际test_material_revisions.py后21项通过；未把未收集计通过。
