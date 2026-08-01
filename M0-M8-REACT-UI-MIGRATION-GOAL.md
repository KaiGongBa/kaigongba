# 开工吧 M0–M8 生产 React UI 迁移执行规格

日期：2026-08-01
目标：将已经确认的 13 个对话端目标界面迁移到生产 React 应用，继续使用真实业务数据与现有业务组件；将“企业与团队”移动到管理端“账号管理”之下；不破坏已经跑通的需求、报价、协议、演示支付、订单、SOP、交付、争议、Agent、Skill 和权限流程。

## 1. 设计真源与代码真源

迁移前必须完整读取：

1. `../product-design-audit/ui-restructure-20260801/migration-baseline.md`
2. `../product-design-audit/page-route-mapping-20260801/mapping-report.md`
3. `../product-design-audit/ui-restructure-20260801/prototype/interaction-inventory-20260801.md`
4. `../product-design-audit/ui-restructure-20260801/prototype/interaction-regression-20260801.md`
5. `../product-design-audit/ui-restructure-20260801/prototype/index.html`
6. `../product-design-audit/ui-restructure-20260801/prototype/app.js`
7. `../product-design-audit/ui-restructure-20260801/prototype/styles.css`
8. 本文件。

实现时以生产代码中的 Repository/API、权限判断、状态机和真实对象 ID 为业务真源；本地原型只是真实 UI、页面结构与交互契约，不是数据真源。

## 2. 范围

主要允许修改：

- `frontend-enterprise/src/App.tsx`
- `frontend-enterprise/src/enums/routes.ts`
- `frontend-enterprise/src/components/AppSidebar.tsx`
- `frontend-enterprise/src/pages/chat/`
- `frontend-enterprise/src/features/marketplace/`
- 为项目中心、交易总览、共享对话端外壳和开小花新增的前端组件、样式与测试
- `backend/` 中仅在现有接口无法提供真实聚合数据时增加只读聚合查询；优先复用现有接口
- 本迁移新增的自动化测试与 QA 证据

允许对管理端做的唯一结构性调整：

- 在“账号管理”中增加二级导航和“企业与团队”入口。
- 复用现有 `AccountsPage` 与 `OrganizationTeamPage`。
- 为兼容权限和嵌入布局进行必要的轻量拆分。

## 3. 保护区

除非修复由本次迁移直接造成的回归，否则不得修改：

- 登录、认证、密码、Token 与现有会话协议
- 支付、退款、结算、争议裁决和资金业务语义
- 需求、报价、协议、订单、SOP、交付、争议状态机
- 多租户与企业数据隔离规则
- 外部 Agent 注册、凭证、任务投递和 Skill 运行时
- StaffDeck 管理端既有页面的功能、图标、信息架构和视觉风格
- 数据库 schema、迁移版本和生产部署配置
- 与本次迁移无关的页面、API、测试和文档

严格禁止：

- 用前端 mock、硬编码数组或原型示例 ID 替代真实业务数据。
- 复制第二套订单、报价、项目、确认或争议状态。
- 删除旧路由或让旧 URL 刷新后失效。
- 为通过测试而删除、跳过、放宽或改写有效测试断言。
- 新增依赖、升级 React/TypeScript/Python 版本或重装依赖，除非用户另行批准。
- 接入真实支付；本轮继续保留演示支付，但不能影响后续真实支付替换边界。
- 自动 push、部署或修改线上环境；阶段提交只保留在本地，等待用户授权发布。

## 4. 目标界面与生产映射

共 13 个目标界面：

1. 项目中心·按员工
2. 项目中心·按项目
3. 员工项目视角
4. 项目详情
5. 交易中心·总览
6. 交易中心·我的需求
7. 交易中心·我的订单
8. 交易中心·待确认
9. 服务经营·我的发布
10. 服务经营·报价管理
11. 服务经营·服务商工作台
12. 开小花·对话
13. 开小花·通知

生产路由原则：

- `/workspace/gallery` 第一轮继续作为项目中心兼容入口。
- `/workspace/projects/agents/:agentId` 为员工项目视角。
- `/enterprise/transactions` 为新增交易总览。
- `/enterprise/demands`、`/enterprise/orders`、`/enterprise/confirmations` 继续复用。
- `/enterprise/orders?perspective=buyer|provider` 保存订单关系视角。
- `/enterprise/publishing`、`/enterprise/provider` 继续复用。
- `/enterprise/orders/:orderId?tab=...` 继续作为唯一订单/项目工作区。
- 开小花没有独立业务路由，在对话端共享外壳中原地展开。

账号与组织路由：

- `/enterprise/accounts`：登录账号；维持系统管理员权限。
- `/enterprise/accounts/organization`：企业与团队；按企业角色决定编辑或只读。
- `/enterprise/organization/team`：只做兼容重定向，目标为 `/enterprise/accounts/organization`。

## 5. 每阶段通用执行协议

每个阶段都按以下顺序执行：

1. `git status --short`，记录阶段开始前工作区。
2. 阅读该阶段涉及的生产组件、测试、迁移规格和原型页面。
3. 先补充或更新失败用例，再实施最小范围代码修改。
4. 运行该阶段定向测试，退出码必须为 0。
5. 运行前端完整测试和生产构建。
6. 如修改后端，运行对应后端测试；没有后端修改时不为“看起来更完整”而改后端。
7. 使用 Codex 应用内浏览器操作真实本地 React 页面，执行鼠标、键盘、刷新、返回和深链验收。
8. 截图保存到 `../product-design-audit/ui-restructure-20260801/qa-react-migration/M<阶段号>/`。
9. 在阶段报告中记录：修改文件、测试命令、退出码、浏览器路径、截图、遗留风险。
10. `git diff --check` 必须通过；确认无越界文件后创建该阶段独立 commit。
11. 阶段没有问题后自动进入下一阶段；不需要等待逐阶段人工确认。

通用前端命令：

```bash
cd frontend-enterprise
npm test
npm run build
npm run i18n:check
npm run config:check
```

相关后端发生修改时：

```bash
cd backend
pytest -q tests/test_marketplace_api.py tests/test_marketplace_management_api.py tests/test_transaction_pretrade_api.py tests/test_enterprise_auth_guards.py
ruff check app tests/test_marketplace_api.py tests/test_marketplace_management_api.py tests/test_transaction_pretrade_api.py tests/test_enterprise_auth_guards.py
```

## 6. M0：冻结迁移基线

### 开发工作

1. 审阅当前工作区已有的 1 个修改文件和 3 个未跟踪测试文件。
2. 确认这些变更属于已经验收的订单工作区与旧路由回归，不混入本次迁移代码。
3. 运行现有 25 项市场、订单与订单工作区定向测试。
4. 运行前端完整测试、构建、i18n 与配置检查。
5. 将确认正确的既有变更提交为 UI 迁移前基线。
6. 保存 Git commit、测试摘要和关键页面基准截图。

### 电脑测试

- 打开 `/enterprise/orders`。
- 切换“我发起的/我承接的”。
- 进入真实订单详情，逐一打开 8 个页签。
- 打开支付单、协议、交付物和争议子路由，再用浏览器返回。
- 打开 AI 员工市场、Skill 市场和企业与团队，确认旧入口仍工作。

### 通过标准

- 当前 4 个未提交文件已被逐项审阅并形成独立基线 commit。
- 既有 25 项定向测试全部通过。
- 前端完整测试与构建通过。
- 没有业务源文件被无理由格式化或重写。

建议 commit：`test: freeze react ui migration baseline`

## 7. M1：建立路由与能力保护网

### 开发工作

1. 建立旧路由可达性枚举测试。
2. 建立 13 个目标界面的新路由/视图契约测试。
3. 建立订单 8 页签、买方/服务方视角、URL 查询参数恢复测试。
4. 建立账号管理员、企业负责人、企业管理员、普通成员访问矩阵测试。
5. 建立“开小花打开不改变当前 URL”的契约测试骨架。

### 电脑测试

- 逐个输入必须保留的旧 URL，执行直接打开和刷新。
- 用浏览器后退/前进检查查询参数与页签恢复。
- 使用键盘 Tab、Enter、Space 操作主导航、页签和订单卡片。

### 通过标准

- 所有旧路由均有自动化断言。
- 13 个目标界面和 8 个订单页签均进入可枚举验收清单。
- 测试本身不依赖固定演示 ID。

建议 commit：`test: lock legacy routes and ui migration contracts`

## 8. M2：移动企业与团队到账号管理

### 开发工作

1. 新增 `AccountManagementLayout` 或等价的管理端二级页面框架。
2. 二级入口为“登录账号”和“企业与团队”。
3. 继续复用 `AccountsPage` 与 `OrganizationTeamPage` 的真实 API 和权限。
4. 新增 `/enterprise/accounts/organization`。
5. 将 `/enterprise/organization/team` 改为保留 search/hash 的兼容重定向。
6. 从对话端“市场与交易”中移除“企业与团队”。
7. 修改账号菜单、服务经营快捷入口和订单说明中的旧链接。
8. 确保没有数字员工的用户也能进入企业与团队。
9. 系统账号权限与企业管理权限分别判断，禁止用 `isEnterpriseAdmin` 代替企业角色。

### 电脑测试

- 管理员进入 `/enterprise/accounts`，切换两个二级入口。
- 企业负责人进入企业与团队并编辑企业资料、邀请成员、修改非负责人角色。
- 普通企业成员进入同一页面，只读查看且看不到无权限操作。
- 直接打开旧地址并确认自动到新地址。
- 在对话端确认市场菜单不再出现企业与团队；账号菜单可进入新地址。

### 通过标准

- 页面归属已经移动，但企业资料、成员、邀请、角色、安全功能没有减少。
- 旧书签和旧业务链接继续有效。
- StaffDeck 其他管理页及图标零变更。

建议 commit：`refactor: move organization team under account management`

## 9. M3：抽取对话端共享外壳

### 开发工作

1. 从 `ChatGalleryPage` 和 `MarketplaceWorkspacePage` 中抽取共享对话端布局。
2. 共享：`SidebarProvider`、`AppSidebar`、会话列表、`ChatDialogs`、内容 `Outlet`。
3. 保持管理端 `Shell` 不变。
4. 保持会话未读、会话筛选、创建对话、切换管理端等原逻辑。
5. 给后续开小花预留共享挂载点，但本阶段不接入假对话。

### 电脑测试

- 从项目中心、AI 员工市场、Skill 市场、订单页之间连续切换。
- 验证会话列表、当前会话、未读状态和侧栏折叠状态不丢失。
- 在窄屏和宽屏切换侧栏。
- 打开员工对话并返回市场页面。

### 通过标准

- 页面视觉和原业务行为不发生非预期变化。
- 对话端只创建一份共享会话状态和侧栏框架。
- 管理端代码路径不受影响。

建议 commit：`refactor: extract conversation workspace shell`

## 10. M4：迁移项目中心

### 开发工作

1. `/workspace/gallery` 内容替换为项目中心，保留旧地址兼容。
2. 增加按员工、按项目两个真实视图。
3. 增加 `/workspace/projects/agents/:agentId` 员工项目视角。
4. 使用真实 Agent、订单、SOP 执行、待办和交付摘要。
5. 连接状态与工作状态分开显示。
6. 所有项目卡片使用真实 `agentId`、`orderId`、`executionId`。
7. 点击项目进入唯一的 `/enterprise/orders/:orderId` 工作区。
8. AI 员工市场继续保留在 `/enterprise/market/agents`。
9. 仅当现有接口无法高效提供聚合数据时增加只读聚合 API；不增加新项目表。

### 电脑测试

- 使用至少 2 个员工、1 个空闲员工、1 个工作中员工和买卖双方订单数据。
- 按员工/按项目切换、搜索、筛选、卡片键盘进入。
- 从员工进入项目，再进入订单详情，并使用浏览器返回恢复原筛选状态。
- 验证无订单、加载、错误、无权限四种状态。

### 通过标准

- 项目中心不再展示数字员工市场内容。
- 页面没有硬编码项目或员工示例。
- AI 员工市场和管理端员工配置均未丢失。

建议 commit：`feat: add real-data project center`

## 11. M5：迁移交易中心与服务经营

### 开发工作

1. 新增 `/enterprise/transactions` 交易总览。
2. 汇总本月采购支出、本月服务收入、累计采购支出、累计服务收入、待付款、待结算、进行中订单和待确认。
3. 指标仅来自真实需求、订单、支付、结算与确认数据；不存在的数据明确为空，不造数。
4. “我的需求”复用现有需求列表和详情流程。
5. “我的订单”保留买方/服务方视角，并把 `perspective` 写入 URL。
6. “待确认”复用现有结构化确认队列。
7. 服务经营只保留“我的发布、报价管理、服务商工作台”三个入口。
8. 我的发布复用 `/enterprise/publishing`。
9. 报价管理复用 `/enterprise/provider` 与报价详情。
10. 服务商工作台使用服务方订单视角和现有订单工作区，不另建履约状态机。

### 电脑测试

- 同一用户分别查看自己作为采购方和服务方的数据，不使用身份切换。
- 发布需求、进入需求详情、报价比较、协议确认和演示支付。
- 打开我发起的与我承接的订单并刷新页面。
- 进入我的发布、服务/Skill 编辑、报价详情与服务订单。
- 检查空状态、搜索、筛选、排序和待确认分类。

### 通过标准

- 收支总览没有重复页面。
- 需求不等于买方订单；商机、报价、协议不混入订单列表。
- “我发起的/我承接的”及真实业务 ID 全部保留。

建议 commit：`feat: migrate transaction and service workspaces`

## 12. M6：将目标 UI 合入订单工作区

### 开发工作

1. 在现有 `OrderWorkspacePage` 上迁移项目详情 UI，不新建第二套详情逻辑。
2. 保留 8 个页签：项目总览、SOP 执行、订单沟通、变更与取消、争议处理、交付物、材料、执行记录。
3. `?tab=` 与浏览器历史同步。
4. 保留采购方/服务方权限差异。
5. 保留支付单、合作协议、交付物详情和争议案件子路由。
6. 保留暂停、恢复、重试、人工接管、交付、验收、修改、材料和消息等真实动作。
7. 保留执行隐私隔离：采购方不能查看乙方提示词、知识库、密钥和内部成本。

### 电脑测试

- 采购账号与服务账号分别打开同一订单。
- 逐一操作 8 个页签并刷新/返回。
- 服务方执行 SOP 控制、请求补料、提交交付物。
- 采购方补充材料、查看版本、验收、要求修改。
- 双方订单沟通、变更、取消和发起平台争议入口。
- 打开支付、协议、交付物和争议子页面后返回。

### 通过标准

- 8 个页签、所有真实动作和子路由一个不少。
- 权限矩阵和状态机没有被 UI 本地状态替代。
- 终态订单、争议中订单、失败执行和无 SOP 四类边界状态可正确显示。

建议 commit：`refactor: apply target ui to order workspace`

## 13. M7：接入开小花全局抽屉

### 开发工作

1. 在对话端共享外壳中挂载开小花入口和右侧抽屉。
2. 任意对话端页面打开抽屉时保持当前路由不变，并自动收起左栏。
3. 提供对话、通知、使用帮助三个页签。
4. 开小花会话与员工私有会话、乙方知识库和提示词隔离。
5. 通知卡片使用真实业务对象 ID 深链到项目、订单、确认或账号设置。
6. 开小花只做导航、解释、客服、前台与待办协助，不替用户完成结构化确认、退款、放款或验收。
7. 保留未读、关闭、重新打开、浏览器返回和当前页面状态。

### 电脑测试

- 在 13 个目标界面逐页打开和关闭开小花。
- 打开前后比较 URL，必须完全一致。
- 展开后检查左栏收起、主内容可用和右下操作不被遮挡。
- 从通知卡片进入真实业务对象，再返回。
- 在员工对话和开小花对话分别发送消息，确认会话数据互不串联。
- 键盘打开、切换页签、发送、关闭并恢复焦点。

### 通过标准

- 开小花不再通过跳转项目中心实现。
- 13 个页面均可原地打开。
- 会话、权限和数据边界通过测试。

建议 commit：`feat: add isolated Kai Xiaohua assistant drawer`

## 14. M8：完整业务回归、视觉验收与交接

### 自动化测试

1. 前端完整 `npm test`。
2. 前端 `npm run build`。
3. i18n 和配置检查。
4. 本迁移涉及后端时运行定向后端测试与 Ruff。
5. 旧路由、13 页面、8 页签、双关系、账号组织权限和开小花专项测试。
6. 检查没有新增 `.skip`、`it.skip`、`describe.skip`、`pytest.mark.skip` 或 `xfail`。

### 电脑业务验收

至少使用两个账号和两个企业角色完成：

1. 用户 A 发布需求、补充澄清、查看 AI 匹配和报价。
2. 用户 B 查看邀请、确认 AI 报价草案并提交报价。
3. 用户 A 比较报价、选标、确认协议和完成演示支付。
4. 系统生成订单；双方进入对应买方/服务方视角。
5. 用户 B 启动 SOP、提交阶段成果、处理补料和人工接管。
6. 用户 A 补充材料、查看交付版本、验收或要求修改。
7. 双方验证订单沟通、变更、取消和平台争议入口。
8. 管理员、企业负责人、普通成员验证账号与团队权限。
9. 每个关键节点从项目中心、交易中心、服务经营和开小花深链进入。

### 视觉与无障碍验收

- 1280×720、1440×900 两个桌面尺寸。
- 浏览器 200% 缩放。
- 鼠标、键盘、焦点恢复和可见焦点。
- 加载、空状态、错误状态、权限不足、超时和终态。
- 与确认原型逐页截图对比；页面结构不变，视觉使用现有开工吧 token 和图标。

### 通过标准

- 所有测试和构建退出码为 0。
- 13 个目标界面、8 个订单页签和全部保留路由均通过。
- 完整双账号流程通过。
- 没有越界文件、无关页面改动或业务 mock。
- 生成最终迁移报告，列出 M0–M8 commit、测试、截图、遗留风险和部署建议。
- 工作区干净；不自动 push 或部署。

建议 commit：`test: complete react ui migration acceptance`

## 15. Goal 完成条件

只有同时满足以下条件才能标记完成：

1. M0–M8 九个阶段均有独立状态、证据与本地 commit。
2. 13 个目标界面均使用生产 React 和真实数据来源。
3. 订单工作区 8 页签、全部旧业务子路由和双关系视角完整保留。
4. 企业与团队已移动至管理端账号管理，旧路由兼容且权限正确。
5. 开小花在全部对话端目标页面原地打开且数据隔离。
6. 前端完整测试、构建、i18n 和配置检查通过。
7. 涉及后端时，对应后端测试和 Ruff 通过。
8. 完整双账号业务验收通过并有截图证据。
9. `git diff --check` 通过，工作区没有未说明改动。
10. 最终报告逐阶段列出 commit、修改文件、测试摘要、浏览器验收和遗留风险。

## 16. Goal 停止条件

遇到以下任一机械条件时停止扩大修改范围，保留证据并向用户报告：

1. 实现需要新增依赖、升级运行时或重装依赖。
2. 需要修改数据库 schema、支付/退款/结算业务语义或现有状态机才能继续。
3. 需要删除旧路由、旧业务组件或 StaffDeck 既有功能/图标。
4. 现有测试产生真实回归，且无法在本阶段范围内修复；禁止通过修改测试、跳过测试或放宽断言解决。
5. `git diff` 出现保护区或无关页面的变更。
6. 真实业务数据无法通过现有接口或只读聚合接口获得，且继续需要建立第二套数据模型。
7. 本地服务、测试账号或必要环境连续无法使用，导致无法形成阶段验收证据。

停止不等于 Goal 完成；必须保持 Goal 未完成状态，并明确阻塞阶段、证据和需要用户决定的事项。
