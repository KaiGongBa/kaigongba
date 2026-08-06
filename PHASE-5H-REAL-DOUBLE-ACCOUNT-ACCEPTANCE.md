# Phase 5H 真实双账号与外接员工验收记录

## 验收结论

2026-08-06 在本地隔离环境通过三个独立账号和真实 API 数据完成以下主链：

1. 甲方发布真实需求。
2. 平台默认大模型在真实服务、能力清单和运行心跳上执行匹配。
3. 平台大模型生成乙方私有 AI 报价草案，乙方负责人确认后发送。
4. 甲方选标，双方分别确认协议，平台使用演示支付生成订单。
5. 乙方启动冻结 SOP，本机 Worker 第 1 次领取任务。
6. 本机 Codex Handler 真实执行并回传结构化结果，平台投影 SOP 节点并自动排队后续节点。

本次仅支付为演示通道；需求、匹配、报价、协议、订单、SOP、外接任务和结果均为真实持久化业务数据。

## 双账号与边界

| 角色 | 账号 | 企业 | 验收操作 |
| --- | --- | --- | --- |
| 甲方 | `qa_phase5h_buyer` | `org_demo_buyer` | 发布需求、选标、确认协议、创建演示支付单 |
| 乙方 | `qa_phase5h_provider` | `org_cloud_ops` | 审核 Manifest、创建员工、发布服务、确认 AI 报价、确认协议、启动 SOP |
| 平台复核员 | `qa_phase5h_reviewer` | 无甲乙方成员关系 | 服务审核和演示支付复核 |

账号密码、Token、配对码、Worker 凭据和租约均未写入此记录或 Git。

## 持久化证据

| 证据 | 结果 |
| --- | --- |
| 需求 | `req_01922cc0ea734703`，最终状态 `contracted` |
| 匹配 | 服务 `aisvc_external_externalagent_149c9fddde034d72`，得分 `86`，引擎 `marketplace_match_v2` |
| 匹配模型审计 | `matching / succeeded`，部署 `aimodel_29350b7e3fdf4f09` |
| AI 报价 | `quote_d997fc7080b34255`，模型审计 `quote_draft / succeeded`，总价 `799.00` |
| 订单 | `order_91b4dc12e9b84946`，绑定本轮外接服务，状态 `in_progress` |
| SOP 运行 | `execrun_6a36ab39201c47cd`，第 1 节点 `succeeded`，第 2 节点已排队 |
| Worker 任务 | `agenttask_0ab473c5a8204cf2`，第 1 次执行 `succeeded` |
| 真实结果 | 非空键 `content` 与 `summary` |
| 结果摘要 | `sha256:efe8d083788ac2df2431ef860baafac12c18bbc362b63a200daee4cb62a6fe96` |

## 验收中发现并修复的问题

1. Worker 连接测试曾上报本地全部 Skill 数量，与平台审核启用数量不一致。现改为上报平台实际启用子集。
2. 元数据型 Skill 的默认输出 Schema 为空对象，无法回传真实交付结果。现提供 `summary + content` 结构化契约，并允许平台传入有界订单上下文。
3. 外接服务解析曾绕过 `online=false` 下线开关，使旧服务仍可参与匹配。现上下线状态在 StaffDeck 和外接员工两种模式下统一生效。
4. 验收脚本曾读取旧字段 `result_json/attempt`，现与真实数据模型 `output_json/attempt_count` 对齐。

## 自动化门禁

- 主应用定向交易、外接 Agent 与执行测试：`40 passed`。
- 主应用后端全量（排除真实飞书进程尖刺用例）：`1552 passed, 4 skipped`。
- 迁移用例在正确 backend 工作目录单独复验：`2 passed`。
- 独立 connector 仓库全量：`74 passed`。
- 主应用本轮文件与 connector：Ruff check 通过、本轮文件格式检查通过。

`test_feishu_process_spike.py` 需访问外部飞书服务，本地发布门禁未将它作为本轮交易与外接员工改动的失败依据。
