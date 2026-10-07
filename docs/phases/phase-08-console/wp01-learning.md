# P8-WP01：操作台阅读与小练习

项目实现：同源操作台、真实PG列表、服务端合成事件绑定、原核查/反馈接口。本人掌握：待验证。零真实模型请求；本包不是新增真实设备或生产身份体系。

阅读顺序：interfaces/console/assets/index.html → app.js（页面状态/事件）→ api.js（HTTP/幂等意图）→ console/routes.py → console/service.py → 原WorkflowService/PerceptionRuntime。Java对照：页面是Controller调用方；console路由是薄Controller；ConsoleService处理用例适配，业务状态仍由原服务/Graph管理。

需要理解：

1. 为什么浏览器只保留选择/表单状态，任务与反馈从PG读取？刷新后为什么要重新连接？
2. expected_revision与request_id各防什么问题？网络超时为什么不能直接换一个请求ID重发？
3. 合成事件的身份、区域与材料版本由哪段代码生成？页面为什么不能自行指定tenant？
4. 为什么材料修订/读取失败后，要先清除旧核查的“当前有效”与反馈权限？
5. 固定的合成业务时间与数据库入库顺序有什么区别？

本人小练习（尚未完成）：从页面填入缺项示例，先补作业位置、再补作业方式，记录v1→v2→v3的截图；指出两次提交对应的API路径与service方法。随后只修改一个页面字段提示并刷新观察变化，解释为什么这不改变后端缺项规则。

下一工作包：P8-WP02用户已授权的阿里云独立部署与远程恢复验收。
