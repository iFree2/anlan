# P8-WP03验证与发布边界

用户2026-10-07明确要求线上使用DeepSeek。材料与事件核查两条链路已发布，公网实际3次DeepSeek请求全部通过；本地HTTP替身测试与云端真实请求证据分别记录。

## 已执行

最终本地CI见live-ci.json/XML：467 passed、0失败/跳过，锁文件、ruff及受检源码前后指纹一致。发布前另用live-wheel-v2.json核对页面资产，因为通用CI指纹未覆盖JS/HTML/CSS。

- live-red.xml：新3项合同测试初次失败，服务配置尚无deepseek_live。
- live-green-v1.xml：3项通过，真实PG＋受控供应商HTTP响应；验证预占先于HTTP、成功请求重放不重复收费、P8-WP03共用账本、错误/耗尽不退回替身、无密钥拒绝启动。
- live-targeted.xml：79项通过，覆盖console、budget、perception及API回归。
- live-history-red.xml：证明live服务仍能向offline历史新增事件（200而预期409）；修复后live-history-green.xml的10项通过，包括旧事件不能新增核查。
- 页面离线模式在本地浏览器实际打开并选择本地访问配置，显示服务端返回的离线/替身模式；JS语法检查通过。后续live云端浏览器验收见live-cloud-browser.json。
- live-wheel.json：旧通用校验器因硬编码要求8份SQL＋1份说明而失败；当次资源逐字节匹配、模块独立导入及9个CLI入口均通过。现有项目实际已有10份SQL。
- live-wheel-v2.json：重建后98份源码/SQL/页面资产逐字节匹配，10份SQL、4份页面资产齐全，隔离目录从wheel导入通过；包含SQL010及service_models。

独立审查发现的历史事件写入与替身成功文案均修正；结果显示区分配置模式、调用预占与已校验响应，预算耗尽不被称为真实请求成功。

## 固定边界

生产账本仍由云端唯一写入，原46次历史不重置；本次包名固定P8-WP03，两链路共享每包10/累计100上限。测试使用独立authorization，未在冻结的本地生产账本预占，未发真实模型HTTP请求。

成功响应后的同request_id重放不新增模型调用；模型响应后checkpoint落盘前中断，显式recover可能再调用并计次，页面已提示。旧offline材料禁止续写或新增事件/核查；既有结果仍可按原版本/currentness规则记录人工反馈。

先前既有SSH密钥和交互密码认证失败；用户明确提供候选密码后，以非交互方式认证成功并核对已固定主机指纹。失败不证明用户本地MobaXterm连接有误，未将管理密码写入仓库/报告。

## 已完成的云端验收

- live-cloud-before.json：原46条逐字段规范化后与首次迁移导出相同，补齐此前缺口。
- live-rollout-safety-v2.json：Linux临时目录＋模拟服务/健康检查9项通过，包括异常临时文件清理和stop失败继续恢复；旧v1也保留。
- live-cloud-prepared.json / live-cloud-activated.json：独立发布、旧依赖复用、私密备份、PID变化、双链路deepseek_live，切换时预算仍46；实际激活一次成功，未执行真实故障回滚演练。
- live-cloud-acceptance.json：公网页面实际材料400token、安全帽3169token、气体2773token，三次成功共6342token；核查响应通过合同验证，三项事实/知识查询ok，两条人工反馈保存；原站摘要、旧任务快照和三份静态资源一致。
- live-cloud-budget-after.json：49/100，47成功/2历史失败/0pending，P8-WP03=3，原46条规范化摘要不变，known token总88095，金额未查。只云端计次，本地账本未调用。
- live-cloud-browser.json：实际模式/余量、真实结果、反馈、刷新令牌清空、重连PG恢复；一次点击发生在连接加载未完成、按钮仍禁用时超时，之后读取状态确认并完成选择，没有因此新增模型调用。截图在聊天展示。

应用源码未变化，沿用已匹配的467项CI与wheel校验；部署脚本另做Linux故障模拟及实际prepare/activate验证。HTTP/TLS、生产认证、真实现场、模型泛化和本人掌握限制继续保留。
