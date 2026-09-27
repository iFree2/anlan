# P6-WP01：从失败层到可证伪假设

AI完成的工程实验与本人掌握分开。个人实践目前待验，不阻塞后续开发。最终实验结果见本包evidence报告，旧P5的0/2不删除。

1. HTTP成功、JSON合法、Pydantic结构通过、引用支持、现场真实，为什么是五种不同结论？
2. 为什么Prompt写“notice必须是X。”可能与Literal的“X”冲突？由Schema生成提示解决什么，又不能保证什么？
3. 为什么只保存Pydantic的type/loc仍可能泄漏输入？extra_forbidden的loc来自哪里？
4. 两个已见样本修订后成功，能否证明原两次失败都是句号造成？缺少什么反事实或原始证据？
5. 网关账本succeeded与应用unsupported_output能否同时成立？为什么失败与取消也不能退还预占额度？

可选练习：在离线HTTP替身中构造一个Schema合法、却把事件关注引用o1的输出；先预测stop_reason，再跑测试并解释为什么不需再请求真实模型。不要读取或粘贴模型凭据。
