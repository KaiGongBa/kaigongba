# 开工吧真实业务 MVP：Codex Vibe Coding 执行方案

> 目标：先跑通一条可投入受控试运行、可重复验收、可审计的完整交易与 AI 交付闭环。除支付渠道外，业务数据均按真实数据标准建设。
> 适用范围：当前 `kaigongba` 仓库。
> 推荐方式：一个阶段一个 `/goal`，一个阶段一个检查点，不使用一个超大 Prompt 承包整个项目。

## 1. 已冻结的 MVP 决策

### 包含

- 保留现有账号密码登录；
- 企业、成员和角色使用真实业务数据；测试环境另外提供一家甲方和一家乙方的测试种子；
- 同一用户可加入多家企业；
- 一个乙方服务商品；
- 甲方发布一条需求；
- AI 推荐乙方并生成推荐理由；
- AI 生成报价草案，乙方确认后才发送；
- 甲方选择报价；
- 双方点击确认平台合作协议；
- 自动生成一个订单和一个里程碑；
- 演示支付：创建正式业务支付单，通过平台管理员按钮模拟支付成功、失败、退款和放款；不发生真实资金流转；
- 订单启动一个冻结的 StaffDeck SOP；
- SOP 中调用一个第三方 Skill；
- 乙方提交一个交付物版本；
- 甲方验收通过、请求修改或发起平台争议；
- 平台记录真实的平台争议处理方案，并驱动演示支付适配器模拟退款/放款结果；
- 甲方、乙方、平台三个最小看板；
- 站内待办和系统事件。

### 明确不包含

- 真实收款、托管、分账、提现和渠道对账；
- 正式电子签章；
- 发票；
- AI 自动发出报价；
- AI 自动作出争议决定；
- 多支付渠道；
- 开放式第三方 Skill 市场；
- 不受信任 Skill 在宿主机直接运行；
- 小程序完整业务端；
- P1 信用、评价、结算、外部 Agent 和完整第三方沙箱。

除支付渠道和资金执行结果外，上述数据均为真实业务数据，不得用前端 mock、内存数据或只读演示 JSON 代替。界面中所有资金操作必须显示“演示支付/不发生真实资金流转”。

## 2. 真实业务验收路径

成功版本必须能使用真实数据库和对象存储重复执行以下 18 步；测试环境可通过测试种子初始化，正式环境不自动写入种子：

1. 甲方账号登录；
2. 进入甲方企业；
3. 发布需求；
4. 平台 AI 匹配到乙方；
5. 乙方收到邀请；
6. AI 生成报价草案；
7. 乙方修改或直接确认报价；
8. 甲方选择报价；
9. 甲方点击确认协议；
10. 乙方点击确认协议；
11. 系统生成订单、里程碑、服务快照、报价快照和 SOP 快照；
12. 管理员通过演示支付适配器把支付单标记为已支付；
13. 订单启动 StaffDeck SOP；
14. SOP 调用一个已审核第三方 Skill，并把结果回传订单；
15. 乙方提交交付物；
16. 甲方选择验收通过、请求修改或发起争议；
17. 平台在争议页查看证据摘要并录入人工处理结果；
18. 三个看板显示一致的订单、执行、交付、支付和争议状态。

## 3. 过渡架构

为了“先跑通”但又不把交易逻辑继续塞进 StaffDeck：

```text
frontend-enterprise
  ├─ 现有 StaffDeck 工作台
  ├─ /buyer/*
  ├─ /seller/*
  └─ /platform/*

backend process A：现有 StaffDeck
  ├─ Agent / SOP / Skill / Knowledge / Tool
  ├─ ExecutionRun / NodeRun
  └─ 内部执行 API + 事件 Outbox

backend process B：交易核心
  ├─ 组织与权限
  ├─ 服务 / 需求 / 报价 / 协议
  ├─ 订单 / 里程碑 / 交付 / 验收
  ├─ 可替换支付适配器 / 平台争议处理
  └─ StaffDeck Gateway + 事件 Inbox
```

两个进程可继续放在一个 Python 项目中：

```text
backend/app/main.py                  # StaffDeck
backend/app/transaction_main.py      # 新交易核心入口
backend/app/transaction/             # 新交易域
backend/app/execution_api/           # StaffDeck 内部执行接口
backend/app/contracts/               # 两端共享的版本化 schema
```

交易核心和 StaffDeck 使用不同的 PostgreSQL 数据库。现有 StaffDeck SQLite 通过一次性迁移工具导入，原库保留为只读备份。两端只通过 API/Outbox 通信，不跨库查询。

真实业务 MVP 使用 PostgreSQL Outbox 轮询保证异步事件持久化；首期暂不引入 Redis。流量扩大后再把 Worker 调度、缓存、分布式锁和限流迁移到 Redis/正式队列。

## 4. 第三方 Skill 的 MVP 安全边界

“可以接入第三方 Skill”在真实业务 MVP 中定义为：

- 只允许管理员手工导入；
- 必须记录来源、版本、SHA-256、权限声明和审核人；
- 可导入多个经管理员审核的无网络、纯计算 Skill，例如文本/CSV 摘要；首个验收使用一个固定测试包；
- 导入后生成不可变版本，订单只引用固定版本和 digest；
- 运行器环境改为最小 allowlist，禁止继承 `APP_SECRET`、模型 Key、渠道密钥等宿主环境变量；
- StaffDeck 整体以非 root 容器运行，根文件系统只读；
- Skill 仅获得临时工作目录，设置 CPU、内存、进程数、文件大小和运行时间上限；
- 默认禁网，不挂载 Docker socket，不挂载宿主项目目录；
- 输出只能写到指定 artifact 目录；
- 运行事件记录 Skill digest、输入摘要、输出摘要、退出码、耗时和资源限制结果。

这是可供真实业务使用的“管理员审核型第三方 Skill 通道”，不是允许任意发布者自动上架的开放式技能市场。需要网络或外部凭据的 Skill 等隔离代理和网络白名单完成后再开放。

## 5. Codex 工作方式

### 开始前的人工作业

当前仓库已有未提交的品牌化改动。开始功能开发前：

1. 运行 `git status --short`；
2. 人工检查并提交当前品牌改动，或创建可恢复的备份；
3. 创建分支 `codex/mvp-v0`；
4. 不允许 Codex reset、checkout 或覆盖这些品牌文件；
5. 每完成一个 goal，先运行验收，再创建一个检查点提交；
6. 下一个 goal 只建立在上一个已通过的检查点上。

### 每个 goal 的固定节奏

1. Codex 先读取 spec 和相关代码并报告计数；
2. 你确认读取结果；
3. Codex 实现；
4. Codex 运行目标测试和回归测试；
5. Codex 展示改动文件、失败项和剩余风险；
6. 你在浏览器走一次当前阶段路径；
7. 通过后提交检查点；
8. 再启动下一个 goal。

不要在同一个 goal 中同时设计领域、实现后端、实现三套 UI、修复旧测试和部署。这样最容易出现“代码很多但闭环没跑通”。

## 6. 时间与阶段

| 阶段 | 内容 | 建议时间 |
|---|---|---:|
| G0 | 编写 MVP SDD、状态机、权限矩阵、任务清单 | 1～2 天 |
| G1 | 清理基线、双 PostgreSQL、本地双进程、StaffDeck 数据迁移、CI 门禁 | 5～8 天 |
| G2 | 组织、服务、需求、匹配、报价、协议、订单、演示支付 | 8～12 天 |
| G3 | StaffDeck 运行实体、SOP 快照、事件回传、第三方 Skill | 8～12 天 |
| G4 | 对象存储、交付、修改、验收、平台争议、三个看板 | 10～15 天 |
| G5 | E2E、测试种子、故障回放、试运行文档 | 5～8 天 |

一个熟悉 Python/React 的技术负责人全职使用 Codex，真实业务 MVP 约 8～12 周；若需要边学代码边做，按 12～16 周安排。该估算不包含真实支付渠道接入和由法律意见引发的协议流程调整。

## 7. Goal 0：先生成可执行 SDD

```text
/goal 为开工吧真实业务 MVP 建立一套可直接驱动后续 Codex 实现的 SDD，定义一条“需求→AI 报价草案→乙方确认→选标→协议点击确认→演示支付适配器→订单 SOP→第三方 Skill→交付→验收或平台争议处理”的纵向闭环；除支付渠道外均使用真实业务数据和正式持久化，本 goal 只写规范，不修改源代码。

First action: 先逐字读取以下文件，然后回报计数：
  - ../开工吧-StaffDeck二次开发可行性与执行方案.md
  - MVP-VIBE-CODING-EXECUTION.md
  - backend/app/db/models.py
  - backend/app/security/auth.py
  - backend/app/security/permissions.py
  - backend/app/core/skill_runtime.py
  - backend/app/core/human_handoff_service.py
  - backend/app/async_jobs.py
  - frontend-enterprise/src/App.tsx
  - frontend-enterprise/src/api/client.ts
报告：现有 SQLModel 表数量、现有用户角色数量、现有前端 Route 数量、MVP 业务验收步骤数、发现的源代码未提交文件数量。等我确认后再继续。

Scope: 只允许新建 specs/mvp-v0/ 下的 proposal.md、design.md、tasks.md、spec.md、state-machines.md、permission-matrix.md 和 api-contracts.md。

Constraints:
  - 不修改 backend/、frontend-enterprise/、README、品牌资产、锁文件和数据库文件。
  - proposal.md 固定写明演示支付不发生真实资金流转。
  - 用户、组织、服务、需求、报价、协议确认、订单、SOP、Skill、交付、验收、争议、文件和看板均使用真实业务数据库/对象存储，不得以前端 mock 或内存数据代替。
  - AI 报价只有乙方确认后才能发送；AI 不得作出争议决定。
  - 第三方 Skill 仅允许管理员导入、固定 digest、无网络、最小环境变量和受限容器运行。
  - 交易核心与 StaffDeck 使用不同数据库和版本化 API/事件通信。
  - spec 中不得使用泛化全量承诺，验收对象必须可计数或可枚举。

Done when:
  1. specs/mvp-v0/ 中存在上述 7 个文档。
  2. spec.md 正好定义 18 个 GIVEN/WHEN/THEN 场景，与 MVP 业务验收路径 18 步一一对应。
  3. state-machines.md 分别定义 requirement、quote、agreement、order、milestone、demo_payment、execution、acceptance、dispute 9 个状态机，每个转换含 actor、guard、side effect 和 forbidden transitions。
  4. permission-matrix.md 覆盖 buyer_owner、buyer_member、seller_admin、delivery_member、platform_ops、platform_finance、platform_dispute 7 个角色。
  5. api-contracts.md 定义交易核心到 StaffDeck 的 5 个命令、StaffDeck 回传事件 envelope、command_id/event_id 幂等规则和错误码。
  6. tasks.md 拆成 G1～G5 五个可独立验收阶段，每个任务注明目标目录、测试文件和验收命令。
  7. 最终 summary 列出 7 个文档的行数、18 个场景标题和仍需人工裁定的问题；git diff 不包含 specs/mvp-v0/ 之外的路径。

Stop if:
  - 需要修改任何现有源代码或品牌文件。
  - 发现演示支付、合同确认或第三方 Skill 边界与本 goal 的 Constraints 冲突。
  - 需要增加新的产品角色或真实支付能力才能写完 18 个场景。
  - git status 出现本 goal 新增规范之外的未知变化。

Use a token budget of 80000 tokens for this goal.
```

## 8. Goal 1：稳定基线和本地双进程

```text
/goal 严格按照 specs/mvp-v0/ 的规范完成 G1：把当前仓库变成可重复启动的 StaffDeck + 交易核心双进程环境，两端分别使用 PostgreSQL，提供现有 StaffDeck SQLite 数据的可验证迁移工具，并将现有后端失败测试从 8 个降为 0。

First action: 逐字读取 specs/mvp-v0/ 下 7 个文档、backend/pyproject.toml、backend/app/main.py、backend/app/db/database.py、scripts/dev.py、frontend-enterprise/vite.config.ts 和 .github/workflows；报告 tasks.md 中 G1 task 数量、允许新增的依赖、当前 pytest 失败测试名和现有未提交文件。等我确认后再实现。

Scope: backend/app/transaction_main.py、backend/app/transaction/infra/、backend/app/db/ 的 PostgreSQL 兼容与迁移入口、backend/tests/transaction/infra/、backend/tests/migrations/、scripts/、前端代理配置、compose.mvp.yml、.github/workflows/；可针对当前 8 个失败测试修改其对应生产代码，但不得进行无关重构。

Constraints:
  - 保留现有 StaffDeck 启动入口；现有 SQLite 原文件不得删除或原地改坏，迁移后作为只读备份。
  - StaffDeck 和交易核心使用两个独立 PostgreSQL 数据库和正式迁移目录。
  - 允许新增 PostgreSQL driver、Alembic 和测试所需依赖；其他新依赖先停止汇报。
  - 不修改或删除现有品牌资产、README 品牌内容和用户未提交改动。
  - 不通过修改 golden fixture、删除测试、skip、xfail、放宽断言或缩短测试范围解决 8 个失败。
  - 前后端锁文件只允许出现已批准依赖对应的机械变化。

Done when:
  1. compose.mvp.yml 能启动 staffdeck-db、transaction-db 两个 PostgreSQL 实例/数据库，healthcheck 均为 healthy。
  2. StaffDeck 与 transaction_main 可在不同端口同时启动，两个 /health 端点均返回 200，并显示不同 app identity。
  3. StaffDeck 和交易核心均能执行从空库升级到 head、降级一个 revision、再次升级到 head，六个命令退出码均为 0。
  4. SQLite→StaffDeck PostgreSQL 迁移工具支持 dry-run、数量/主键/关键 digest 校验和重复执行；源 SQLite 未被修改，失败时 PostgreSQL 导入事务回滚。
  5. backend/.venv/bin/python -m pytest -q 退出码 0，failed=0，且没有新增 skipped/xfail。
  6. npm --prefix frontend-enterprise run build 退出码 0。
  7. CI workflow 包含后端 pytest、前端 build、双数据库 migration smoke 和 SQLite 导入 dry-run 四个门禁。
  8. scripts/dev.py 或新增的明确入口能一条命令启动 MVP 本地环境；MVP-VIBE-CODING-EXECUTION.md 补充实际命令。

Stop if:
  - 修复旧测试需要重写 checked-in golden fixture 或测试断言。
  - PostgreSQL 迁移无法在不修改源 SQLite 的前提下完成，或 dry-run 发现无法映射/校验的数据。
  - 需要新增本 goal 未授权的运行时依赖。
  - 现有通过测试出现 regression；不要靠修改测试或增加 skip 解决。
  - git diff 出现与 G1 无关的品牌资产或业务页面。

Use a token budget of 140000 tokens for this goal.
```

## 9. Goal 2：交易前半段与演示支付

```text
/goal 严格按照 specs/mvp-v0/ 完成 G2：实现组织、服务、需求、AI 匹配、AI 报价草案与乙方确认、选标、协议点击确认、订单生成、单里程碑和演示支付闭环。

First action: 读取 specs/mvp-v0/ 下 7 个文档、backend/app/security/、backend/app/api/auth.py、backend/app/transaction/、frontend-enterprise/src/App.tsx 和 frontend-enterprise/src/auth.ts；报告 G2 task 数量、涉及的状态机数量、权限矩阵中 G2 相关 allow/deny 数量和计划新增的数据表数量。等我确认后再实现。

Scope: backend/app/transaction/{identity,organizations,catalog,requirements,quotes,agreements,orders,payments_demo,audit}/、backend/tests/transaction/、frontend-enterprise/src/pages/{buyer,seller,platform}/、frontend-enterprise/src/api/transaction-client.ts、必要路由和导航。

Constraints:
  - 继续使用现有账号密码登录方式；允许交易核心通过受控内部接口解析当前用户身份。
  - 甲方/乙方是 organization/order party，不写入 User 单一 role。
  - AI 只能生成 match recommendation 和 quote draft；只有 seller_admin 可确认并发送报价。
  - 双方协议确认是结构化记录，不从聊天文字推断。
  - 组织、服务、需求、匹配、报价、协议、订单和里程碑写入真实 PostgreSQL 表，前端不得使用 mock 数据或 localStorage 作为真相源。
  - 支付采用 PaymentProvider 接口；首个 DemoPaymentProvider 不访问外部网络、不接收真实支付信息，支付相关页面标注“演示支付”。
  - 金额使用整数分或 NUMERIC，禁止 float。
  - 状态更新、audit event 和 Outbox 写入同一事务。
  - 不实现 StaffDeck 运行、交付、争议和三套完整看板；这些属于 G3/G4。

Done when:
  1. G2 数据库 migration 可升级/降级/再升级，退出码均为 0。
  2. 后端集成测试覆盖：同一用户加入两家企业、跨企业访问拒绝、AI 草案不能被甲方看到、乙方确认后报价可见、并发选标只有一个成功、双方确认后生成一个订单和一个里程碑。
  3. 订单生成时保存 service、requirement、quote、agreement、milestone 五类快照及 digest。
  4. 演示支付支持 created、paid、failed、refund_requested、refunded 五个状态；重复 simulate-paid 请求不会重复写资金流水。
  5. 浏览器可使用数据库中的真实业务记录走通业务验收路径第 1～12 步，并在 platform 页面看到结构化时间线；刷新或服务重启后数据仍存在。
  6. backend/.venv/bin/python -m pytest -q 退出码 0，failed=0，无新增 skip/xfail。
  7. npm --prefix frontend-enterprise run build 退出码 0；新增 buyer/seller/platform 路由使用 lazy loading。

Stop if:
  - 需要真实支付渠道、真实银行卡数据或外部电子签约服务。
  - 实现要求把 User.role 扩展成甲方/乙方永久角色。
  - 现有测试开始失败；不要靠改测试、skip 或 xfail 解决。
  - 需要新增 specs/mvp-v0/ 未批准的生产依赖。
  - 任一金额字段只能通过 float 实现。

Use a token budget of 190000 tokens for this goal.
```

## 10. Goal 3：StaffDeck 订单执行与第三方 Skill

```text
/goal 严格按照 specs/mvp-v0/ 完成 G3：让已支付订单以冻结 SOP 快照启动 StaffDeck ExecutionRun，执行一个经管理员审核、固定 digest 的第三方 Skill，并可靠回传节点状态和 artifact。

First action: 读取 specs/mvp-v0/ 下 7 个文档、backend/app/core/skill_runtime.py、backend/app/core/agent_loop.py、backend/app/general_skills/runner.py、backend/app/capabilities/contracts.py、backend/app/observability/event_log.py 和 backend/app/transaction/orders/；报告 G3 task 数量、当前 Skill 运行时继承的环境变量来源、现有运行/事件表数量和准备新增的 API/事件类型数量。等我确认后再实现。

Scope: backend/app/execution_api/、backend/app/contracts/、backend/app/transaction/execution_gateway/、backend/app/general_skills/runner.py 的环境隔离与资源限制、backend/tests/execution_api/、backend/tests/transaction/execution/、一个 tests/fixtures/third_party_skills/ 下的无网络测试 Skill，以及管理员第三方 Skill 导入/审核接口。

Constraints:
  - StaffDeck 与交易核心不跨库查询。
  - 创建运行、暂停、恢复、取消、节点重试五个命令均使用 command_id 幂等。
  - 回传事件至少一次投递；交易核心按 event_id 去重并按 sequence 检测乱序。
  - StaffDeck 服务身份无权调用协议确认、验收、演示支付和平台争议决定端点。
  - 第三方 Skill 只能管理员导入和审核；订单引用固定 version + sha256。
  - Skill 运行环境使用最小 allowlist，不继承 APP_SECRET、数据库 URL、模型 Key、渠道密钥或完整 os.environ。
  - 第三方 Skill 默认禁网、只读输入、仅写指定 artifact 目录，设置时间/CPU/内存/进程/文件大小限制。
  - 不把 Prompt、知识库全文、密钥或内部成本回传给甲方。

Done when:
  1. 新增持久化 ExecutionRun、NodeRun、ExecutionEvent、SkillPackageVersion、SkillReview、OutboxEvent，migration 可升级/降级/再升级。
  2. 同一 order/milestone/snapshot 的重复启动命令只创建一个 ExecutionRun。
  3. 管理员可导入多个第三方 Skill 版本并查看来源、版本、sha256、权限和审核状态；未审核版本无法执行，已被订单引用的版本不可覆盖。
  4. 自动化测试证明 Skill 子进程环境中不存在 APP_SECRET、数据库 URL和模型 API Key，并且超时/超内存/越界写文件至少各有一个拒绝测试。
  5. 重复、乱序和延迟执行事件不会回滚订单执行投影；中断 transaction worker 后恢复可继续消费 Outbox。
  6. 浏览器可使用持久化订单和 Skill 版本走通业务验收路径第 13～14 步，并在三类 DTO 中看到不同字段投影；服务重启后运行历史仍存在。
  7. backend/.venv/bin/python -m pytest -q 退出码 0，failed=0，无新增 skip/xfail；npm --prefix frontend-enterprise run build 退出码 0。

Stop if:
  - 资源限制必须通过 privileged container、Docker socket 或宿主项目目录挂载实现。
  - 第三方 Skill 必须读取 allowlist 之外的宿主环境变量或访问未批准网络。
  - StaffDeck 需要直接写交易核心数据库。
  - 现有测试开始失败；不要靠改测试、golden fixture、skip 或 xfail 解决。
  - 需要新增未在 specs/mvp-v0/ 批准的生产依赖。

Use a token budget of 180000 tokens for this goal.
```

## 11. Goal 4：交付、验收、平台争议处理和看板

```text
/goal 严格按照 specs/mvp-v0/ 完成 G4：实现交付版本、修改申请、结构化验收、平台争议处理、站内待办，以及甲方/乙方/平台三个最小看板。

First action: 读取 specs/mvp-v0/ 下 7 个文档、backend/app/transaction/、frontend-enterprise/src/pages/{buyer,seller,platform}/ 和现有 dashboard/trace 页面；报告 G4 task 数量、业务验收路径第 15～18 步对应的场景、三个看板字段差异数量和需要新增的数据表数量。等我确认后再实现。

Scope: backend/app/transaction/{deliverables,acceptance,disputes,notifications,projections}/、backend/tests/transaction/、frontend-enterprise/src/pages/{buyer,seller,platform}/ 和共享订单组件。

Constraints:
  - 交付物每次提交创建新版本，禁止覆盖旧版本。
  - 文件使用 S3 兼容对象存储；本地环境通过 MinIO，正式环境通过配置切换服务，不允许把文件二进制存 PostgreSQL。
  - 上传记录 organization/order/milestone、visibility、mime、size、sha256、scan_status 和 uploader；下载必须先做服务端 ACL，再签发短期 URL。
  - 验收通过、请求修改、发起争议为三个结构化命令。
  - 平台争议处理不是 AI 仲裁；AI 仅生成引用 evidence_id 的证据摘要。
  - 争议案件、证据、补充材料、处理方案、申诉和结案均为真实业务记录；争议期间支付适配器的 release/refund 状态冻结，平台人工决定后才调用演示支付适配器。
  - 甲方看板不能看到 Prompt、知识全文、Skill 源码、密钥、内部成本和乙方内部审核。
  - 三个看板使用同一事实投影，不分别复制状态判断。
  - 不执行真实退款或放款；平台争议处理结果不得声称等同于法定仲裁或司法裁判。

Done when:
  1. MinIO/S3 healthcheck 通过；交付、交付版本、修改申请、验收、争议、证据、决定、通知、文件元数据和查询投影的 migration 可升级/降级/再升级。
  2. 自动化测试覆盖交付两版本、修改后重新提交、验收幂等、争议冻结、证据自动归档、人工处理结果和跨角色字段隐藏。
  3. 争议证据清单包含 agreement、quote、order snapshot、order messages、deliverable versions、acceptance records、execution events 七类引用及 sha256。
  4. 三个看板分别实现 MVP-VIBE-CODING-EXECUTION.md 中定义的角色视图，且共用状态标签和进度组件。
  5. 浏览器可使用真实持久化数据走通业务验收路径第 15～18 步，验收路径和争议路径各生成一份文字验证记录；刷新和服务重启后记录与文件仍可访问。
  6. backend/.venv/bin/python -m pytest -q 退出码 0，failed=0，无新增 skip/xfail。
  7. npm --prefix frontend-enterprise run build 退出码 0；前端主 bundle 不因新增三看板增长超过 G1 基线的 25%。

Stop if:
  - 平台争议决定必须由 AI 自动生成或执行。
  - 文件 ACL 只能依赖前端隐藏。
  - StaffDeck 被要求执行验收、退款、放款或争议决定。
  - 现有测试开始失败；不要靠修改测试、skip 或 xfail 解决。
  - 需要真实支付或正式电子签章；新增 S3/MinIO 客户端之外的生产依赖需先汇报。

Use a token budget of 190000 tokens for this goal.
```

## 12. Goal 5：可重复验收和试运行前检查

```text
/goal 严格按照 specs/mvp-v0/ 完成 G5：把开工吧真实业务 MVP 制作为一条可从空环境重复启动、可由自动化和人工共同验收的 18 步业务闭环；除支付 Provider 为模拟实现外，业务读写使用真实 PostgreSQL 和对象存储。

First action: 读取 specs/mvp-v0/ 下 7 个文档、MVP-VIBE-CODING-EXECUTION.md、所有 transaction/execution 测试、compose.mvp.yml 和现有启动脚本；报告 18 个场景中已有自动化覆盖数量、缺失数量、当前启动命令和当前数据库 migration 数量。等我确认后再实现。

Scope: tests/e2e/、backend/tests/transaction/e2e/、仅限测试/预发环境的 seed、scripts/mvp_*、MVP-ACCEPTANCE-RUNBOOK.md、MVP-VERIFICATION.md，以及为修复 E2E 暴露缺陷所必需的最小生产代码。

Constraints:
  - 不增加新的业务功能。
  - 不把 E2E 失败通过 sleep 加长、隐藏异常、重试整个套件或放宽断言解决。
  - 固定 seed 只能在测试/预发环境显式执行，正式环境启动不得自动写入；seed 不能包含真实个人信息、支付信息或密钥。
  - 只有支付相关页面标注“演示支付”；协议确认、订单、交付、验收和平台争议处理不得标成演示数据。
  - 不重写已有单元/集成测试；仅可新增 E2E 和修复生产缺陷。

Done when:
  1. 一条明确命令能从空数据库启动 StaffDeck、交易核心、PostgreSQL 和前端，并完成 healthcheck。
  2. 一条仅限测试环境的 seed 命令创建两家测试企业、7 个角色账号、一个服务、一个已审核第三方 Skill 和一个测试协议版本；正式环境配置下执行该命令必须拒绝。
  3. 自动化 E2E 覆盖 18 个场景中的至少 15 个；剩余最多 3 个必须在 MVP-ACCEPTANCE-RUNBOOK.md 有逐步人工验证。
  4. 支付回放测试覆盖重复 paid、failed 后迟到 paid、重复 refund 和争议期间 refund/release 四种情况。
  5. 执行回放测试覆盖 StaffDeck 重启、transaction worker 重启、重复事件、乱序事件和 Skill 超时五种情况。
  6. backend/.venv/bin/python -m pytest -q 退出码 0，failed=0，无新增 skip/xfail；npm --prefix frontend-enterprise run build 退出码 0。
  7. MVP-VERIFICATION.md 逐项列出 18 步的自动/人工证据、命令、退出码、截图路径或页面路由，并明确列出生产化前阻断项。
  8. 最终 summary 给出启动耗时、测试总数、E2E 覆盖数、已知限制和完整业务验收入口。

Stop if:
  - 除支付渠道外，任一业务模块只能依赖前端 mock、内存数据或测试 seed 才能运行。
  - 需要真实支付、正式电子签章、生产域名或网络型第三方 Skill 凭据才能完成验收。
  - 任一场景只能通过手工改数据库状态完成。
  - 现有测试开始失败；不要靠修改测试、skip、xfail 或降低覆盖解决。
  - E2E 需要新增未批准生产依赖。
  - 发现跨企业数据泄漏、Skill 获得宿主密钥或金额重复记账。

Use a token budget of 150000 tokens for this goal.
```

## 13. 人工验收检查点

每个 goal 结束后只判断以下问题：

### G0

- 18 步是否与实际业务验收路径一致？
- 九个状态机是否存在业务歧义？
- 七个角色是否足够？

### G1

- 能否在新机器按文档启动？
- 现有 8 个失败是否真正清零？
- 品牌改动是否完整保留？

### G2

- 甲乙方是否真的是组织身份？
- AI 报价是否必须经乙方确认？
- 订单快照是否在模板修改后保持不变？
- 支付相关页面是否明确标注“演示支付”，其他页面是否使用真实业务数据？

### G3

- 第三方 Skill 是否固定 digest？
- 是否真的看不到宿主密钥？
- 重复启动/事件是否不会重复执行？
- 甲方 DTO 是否只显示公开摘要？

### G4

- 验收是否是结构化命令？
- 争议是否冻结支付适配器资金结果？
- 文件是否进入对象存储并经过服务端 ACL？
- 证据是否引用固定版本？
- 三个看板状态是否一致？

### G5

- 能否从空数据库和空对象存储重复验收？
- 不手改数据库能否完成两条分支：正常验收、平台争议？
- 重启/重复/乱序是否仍能恢复？
- 正式环境是否禁止自动写入测试种子？
- 验证文档是否明确标出支付仍不可用于真实资金？

## 14. 跑通后再做的生产化阶段

真实业务 MVP 通过后，再另开 goal 处理：

1. PostgreSQL Outbox worker → 正式任务队列/Redis；
2. 演示支付 Provider → 单一持牌渠道 Provider；
3. 点击确认 → 根据法律意见补强证据或接电子签约；
4. 无网络审核型 Skill → 支持网络白名单和外部凭据的隔离执行集群；
5. 站内通知 → 小程序订阅消息；
6. 基础审计 → 不可修改审计和完整财务账本；
7. 支付回调、退款、分账、结算、对账与差错处理；
8. 压力、安全、灾备与恢复演练。

不要在真实业务 MVP 跑通前同时启动这些扩展 goal；但真实支付接入前必须完成支付专项设计、渠道联调和法律/财务评审。
