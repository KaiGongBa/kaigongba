# 3F SOP 执行、人工接管与第三方 Skill 审核

## 已实现

- 订单里程碑启动时冻结 SOP 内容、版本和 SHA-256 digest，后续修改 StaffDeck 模板不影响已成交订单。
- 执行记录持久化：`ExecutionRun` / `NodeRun` / `ExecutionEvent`，包含节点顺序、尝试次数、进度、异常和人工接管人。
- 执行命令支持启动、暂停、恢复、终止、失败重试、人工接管和人工完成，所有命令使用 `command_id` 幂等。
- StaffDeck 内部回传使用服务身份验证，`event_id` 去重，`source_sequence` 防止乱序事件回滚状态。
- 回传事件白名单仅包含运行、节点、进度和产物事件；支付、验收、争议、退款和放款事件不能由 StaffDeck 调用。
- 第三方 Skill 导入时生成不可覆盖的 package digest，经平台审核通过后才能绑定订单执行。
- 甲方投影不返回 Skill 源标识、提示词、知识库、密钥、内部异常和成本；乙方负责人才拥有执行控制权。
- 订单工作台新增真实「SOP 执行」页签，包含执行摘要、冻结版本、进度、节点轨迹、事件、人工接管和权限隔离说明。

## 数据库与边界

- Alembic revision: `20260731_0006`.
- 新增六张表：SOP 快照、Skill package 固定版本、Skill 审核、执行主记录、节点记录和执行事件。
- 执行命令通过现有 Outbox 写入可靠消息，与交易状态同库提交。
- 执行成功只表示 SOP 完成，不会自动将里程碑验收、不会改变支付或结算状态。

## 验证结果

- 3F 及市场/交易/迁移定向回归：`25 passed`.
- StaffDeck 真实 socket 回归（设置 `NO_PROXY=127.0.0.1,localhost`）：`4 passed`.
- 前端测试：`15 passed`.
- 前端 production build：通过，仅保留既有主 chunk 大小告警。
- 全量后端：`1230 passed / 9 failed`；其中 4 项为本机代理导致的 localhost 502，加 `NO_PROXY` 后全部通过；剩余 5 项与 3E 记录一致，为 3 项 GT13 legacy fixture 、1 项旧模型输出上限断言和 1 项静态 MIME 日志断言。
- 本地浏览器验收：采购方可见 SOP 页签、执行边界和未启动空状态，不显示乙方控制按钮；控制台无 error/warning。

final result: passed
