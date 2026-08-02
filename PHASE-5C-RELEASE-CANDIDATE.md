# 阶段 5C：预发布候选版与全链路稳定性

## 目标

把 5A 的非支付生产底座和 5B/M0–M8 的生产 React 页面收敛成可重复验证的候选版。
本阶段不增加第二套业务模型，不改变页面信息架构，也不接入真实支付。

## 固定业务边界

- 需求、澄清、AI 匹配、AI 报价、乙方确认、选标、协议、订单、SOP、材料、交付、验收和争议继续使用现有 Repository/API、状态机和对象 ID。
- 支付渠道仍为 `demo`；支付单、回调事件、订单和里程碑继续是真实持久化记录。
- 平台争议处理继续由人工形成处理决定并由另一名管理员复核；AI 只整理证据。
- StaffDeck 与交易核心保持服务和数据库边界；外部 Agent、Skill、知识库、密钥和内部成本权限不放宽。
- 预发布烟测只执行登录和只读查询，不创建需求、不提交报价、不操作资金、不改状态。

## 5C 发布门禁

本地候选版门禁：

```bash
./scripts/phase5c_verify.sh
```

包含：

1. `git diff --check` 和新增跳过测试检查；
2. 前端完整测试、构建、i18n 和 Vite 配置检查；
3. 后端完整 Ruff 与 pytest；
4. 5C 发布资产契约检查；
5. 生成包含 commit、版本、迁移 head、支付边界和工作区状态的发布清单。

包含 PostgreSQL、Redis、MinIO、双服务、压力和恢复演练的完整门禁：

```bash
./scripts/phase5c_verify.sh --full-infra
```

该模式会继续调用已经验收的 `scripts/phase5a_verify.sh`，不建立另一套基础设施脚本。

## 预发布只读双账号烟测

烟测不保存或输出密码、Token，只在报告中记录 HTTP 结果和业务边界。必须显式提供：

```bash
export KGB_PHASE5C_BASE_URL=https://staging.example.com
export KGB_PHASE5C_TENANT_ID=tenant_demo
export KGB_PHASE5C_BUYER_USERNAME=...
export KGB_PHASE5C_BUYER_PASSWORD=...
export KGB_PHASE5C_BUYER_ORGANIZATION_ID=...
export KGB_PHASE5C_PROVIDER_USERNAME=...
export KGB_PHASE5C_PROVIDER_PASSWORD=...
export KGB_PHASE5C_PROVIDER_ORGANIZATION_ID=...
export KGB_PHASE5C_ADMIN_USERNAME=...
export KGB_PHASE5C_ADMIN_PASSWORD=...
export KGB_PHASE5C_ORDER_ID=...
export KGB_PHASE5C_DISPUTE_ID=...
python3 scripts/phase5c_smoke.py
```

检查内容：

- `/api/health` 与 `/api/ready`；
- 采购方、服务方、平台管理员分别登录；
- 同一订单的 buyer/provider 两个真实视角；
- 双方读取自己的争议案件为 200，伪装对方企业为 403；
- 普通用户读取平台争议后台为 403，管理员为 200；
- AI 员工市场、Skill 市场与外部 Agent 管理只读入口；
- 响应中演示支付边界仍清晰存在。

## 电脑业务验收

在自动化门禁通过后，使用应用内浏览器执行：

1. 甲方：需求、澄清、匹配、报价比较、协议、订单和争议深链；
2. 乙方：邀请、AI 报价确认、服务方订单、SOP、材料和交付；
3. 管理员：账号、团队、交易监管和平台争议处理；
4. 普通成员：账号与组织权限、跨企业和平台后台拒绝；
5. 刷新、返回、前进、重复点击、键盘和焦点恢复；
6. 1280×720、1440×900 和 200% 等效布局；
7. 服务重启后登录、订单深链和只读烟测仍可恢复。

正常结案和争议结案的完整状态变更流程由现有集成测试及 3H 验收数据承担；预发布环境不重复制造资金动作。

## 通过标准

- 所有自动化命令退出码为 0，且没有新增 skip/xfail。
- 发布清单可复现当前 commit、迁移和支付边界。
- 双账号烟测只读且权限结果为 200/403 预期组合。
- 真实页面、旧路由、8 个订单页签、市场、外部 Agent 和开小花均可访问。
- 没有 schema、依赖、真实支付、生产密钥或线上环境变更。
- 形成 5C 验收报告和独立本地 commit；推送、PR、预发布部署需另行授权。
