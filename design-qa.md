# StaffDeck SD1 UI QA

Source:
- Figma file `03XlzJQ1dFYdlDWBR4Mlg4`, page node `0:1`
- Covered SD1 frames: `1:2892`, `1:765`, `1:1462`, `1:2165`, `1:68`, `1:6578`, `1:3713`, `1:3425`, `1:5883`, `1:7470`, `1:3975`, `1:4614`, `1:4286`, `1:5013`, `1:5409`

Implementation checkpoints:
- Chat gallery and selected-session states: `/private/tmp/StaffDeck-sd1-qa/01-chat-gallery-switch.png` through `/private/tmp/StaffDeck-sd1-qa/15-chat-stopped-or-idle.png`
- Figma reference exports: `/private/tmp/StaffDeck-figma-sd1/01-figma-1-2892.png` through `/private/tmp/StaffDeck-figma-sd1/15-figma-1-5409.png`
- Visual comparison contact sheet: `/private/tmp/StaffDeck-sd1-visual-diff/overview-15-scenarios.png`
- Visual comparison report: `/private/tmp/StaffDeck-sd1-visual-diff/visual-diff-report.json`
- Enterprise employee roster: `/private/tmp/StaffDeck-sd1-qa/02-enterprise-agents-collapsed.png` (legacy filename; Figma node `1:765` is expanded), `/private/tmp/StaffDeck-sd1-qa/05-enterprise-agents-expanded.png`, `/private/tmp/StaffDeck-sd1-qa/09-enterprise-agents-collapsed-reference.png`
- Enterprise employee profile: `/private/tmp/StaffDeck-sd1-qa/06-enterprise-dashboard-expanded.png`, `/private/tmp/StaffDeck-sd1-qa/10-enterprise-dashboard-collapsed.png`
- Dark and responsive checks: `/private/tmp/StaffDeck-sd1-qa/20-dark-chat-input.png`, `/private/tmp/StaffDeck-sd1-qa/21-dark-enterprise-dashboard.png`, `/private/tmp/StaffDeck-sd1-qa/22-mobile-chat-input.png`, `/private/tmp/StaffDeck-sd1-qa/23-mobile-enterprise-agents.png`
- Machine-readable report: `/private/tmp/StaffDeck-sd1-qa/report.json`

Browser QA summary:
- 23 browser states checked: all 15 SD1 frames, 4 enterprise regression pages, 2 dark-mode pages, and 2 narrow-screen pages.
- Figma metadata was checked for all 15 nodes. Important interaction-state corrections: `1:2165` is the chat gallery employee-filter dropdown state, `1:4286` is an expanded-sidebar model-dropdown input state, and only `1:5883` is the collapsed enterprise employee roster; `1:765` and `1:68` are expanded-sidebar roster states.
- Formal API data path used: `/api/auth/login`, `/api/chat/agents`, `/api/chat/sessions`, `/api/enterprise/agents`, and page-owned enterprise/chat API calls.
- Layout checks passed: no horizontal overflow, no visible error toast, no pageerror, key 1440x900 chat dimensions matched SD1 (`72/220` sidebar, `56` header, `570` empty state, `1078/960 x 100` composer).
- In-app Browser checks verified `/chat/gallery` at expanded `220px` sidebar with `所有员工` active, visible employee-filter dropdown, top-right `切换主题`/`刷新页面` only, `/enterprise/agents` summary labels, model-dropdown input state, and dark enterprise dashboard inversion.
- Chat polling was constrained to current/running sessions to prevent request storms and stacked `Failed to fetch` errors.
- Enterprise knowledge page now suppresses non-visible OKF version probes during automatic page load.
- Follow-up in-app browser checks matched SD1 top-right actions (`sun`/`refresh`), collapsed chat bottom icon, and composer shallow border/shadow.
- Dark-mode checks verified enterprise dashboard/agents and chat surfaces all invert their main content areas, not only the sidebars.

Automated checks:
- `npm --prefix frontend-enterprise run build` -> passed
- `node /private/tmp/codex-playwright/sd1-qa.mjs` -> 23 total, 0 failures

Final result: passed

---

# 5B 页面重构设计 QA

日期：2026-08-01
结果：**PASSED**

## 验收范围

- 采购方 / 服务方双角色订单列表
- 服务商工作台
- 结案订单工作区
- 平台交易监管
- 平台争议处理列表
- Skill 市场与外部 Agent 接入回归

本轮沿用现有开工吧布局、品牌、图标、颜色、间距和组件语言；没有删除 StaffDeck 原有功能、路由、图标或品牌资产，也没有新增重复页面。

## 参考与实现证据

参考截图：

- `.artifacts/preacceptance-20260801/05-provider-workbench.png`
- `.artifacts/preacceptance-20260801/06-dual-role-orders.png`
- `.artifacts/preacceptance-20260801/10-platform-disputes.png`
- `.artifacts/preacceptance-20260801/11-transaction-supervision.png`

最终实现截图：

- `.artifacts/5b-orders-provider.png`
- `.artifacts/5b-provider-workbench.png`
- `.artifacts/5b-order-workspace-closed.png`
- `.artifacts/5b-transaction-supervision.png`
- `.artifacts/5b-platform-disputes.png`
- `.artifacts/5b-skill-market.png`
- `.artifacts/5b-external-agent-connect.png`

对照图：

- `.artifacts/5b-orders-comparison-padded.png`
- `.artifacts/5b-orders-dense-comparison.png`

浏览器实现截图使用 1229 × 846 视口、1x 密度；参考图为 1229 × 994。全页对照通过底部留白补齐高度，未对实现截图进行非等比拉伸。

## 对照迭代记录

1. 基线页面存在重复统计数字、无实际作用的类别 / 时间 / 风险筛选、原始英文资金状态、已结案订单仍显示 0% 与待办等问题。
2. 订单列表收敛为真实状态筛选和 6 组业务信息，合并角色与订单、里程碑与进度、金额与结算状态；保留原品牌与页面骨架。
3. 服务商工作台将三组队列改为互斥标签页，并增加真实服务商品、承接订单入口；未入驻企业显示明确入驻动作。
4. 订单工作区增加终态横幅，结案后投影为 100%、节点 3/3、0 待办；SOP、交付物和材料空状态均改为不可继续执行的终态语义。
5. 平台交易监管与争议列表统一中文支付 / 结算 / 执行状态，并显示真实结案时间；关闭态不再显示“尚未启动”或可继续操作的暗示。

## 最终检查

- 数据库：Alembic `20260802_0015 (head)`；`PRAGMA integrity_check` 返回 `ok`；6 个网页账号均有且仅有 1 个私有默认数字员工。
- 历史结案单：订单 `completed / 100% / 3`，待办 `0`，3 个里程碑均为 `closed_by_dispute`。
- 进程：无 `dev_supervisor`；仅保留一组 Uvicorn reload 父子进程和一个 Vite 进程。
- 后端回归：28 项通过，覆盖争议结案重放、Skill 市场、市场管理、外部 Agent 和 Skill 包安全。
- 前端测试：15 项通过；生产构建通过。
- 浏览器：Skill 市场加载 7 个真实 Skill，6 个可安装入口；外部 Agent 五步长期接入流程可访问。
- 控制台：结案订单、平台监管、争议列表、Skill 市场、外部 Agent 页面均无 error / warning。
- 可访问性：新增筛选、标签、列表行操作与关闭按钮具备可访问名称或标准 ARIA 状态。

唯一非阻塞提示是 Vite 的主包体积告警；不影响本轮功能与页面验收，后续可在性能阶段做代码分包。
