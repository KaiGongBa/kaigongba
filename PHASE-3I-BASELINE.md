# 阶段 3I 基线与实施边界

## 当前基线

- 业务阶段 3A～3H 已存在于当前未提交工作树；本阶段不得重置、覆盖或删除既有 StaffDeck 功能、图标和开工吧品牌资源。
- 当前开发入口为合并式 `app.main`，同时承载 StaffDeck 与交易 API。
- 当前默认数据库为 `backend/skill_agent_loop.db`，使用 SQLite；代码已支持 PostgreSQL URL 和 psycopg3，但此前没有真实 PostgreSQL 迁移门禁。
- Alembic 当前包含 `20260731_0001`～`20260731_0008` 共 8 个 revision。
- 当前订单文件体写入本地私有目录，数据库只保存元数据和 SHA-256。
- 当前争议双账号验收案件为 `DSP2026073116435748E1`，结案和重放幂等均已通过。

## 3I 实施顺序

1. 禁止预发/生产使用 `create_all` 和自动演示种子；部署通过独立迁移任务升级，应用启动只验证 revision。
2. 使用真实 PostgreSQL 验证 head、回退一个 revision、再次升级 head。
3. 将合并式入口拆为 StaffDeck 与交易核心两个应用入口，并消除交易域对 StaffDeck 表的直接查询。
4. 把订单文件适配为本地和 S3/MinIO 两种 Provider，下载仍先经过服务端 ACL。
5. 提供测试/预发专用种子和完整 E2E；生产配置必须拒绝执行种子。
6. 形成部署、迁移、回滚和验收文档后再进入 3J。

## 当前实施结果（2026-08-01）

- 已建立预发/生产安全门禁：禁止 `create_all`、自动演示种子、默认应用密钥和缺失的内部服务密钥。
- PostgreSQL 已在真实容器中完成 `head → 0007 → head` 回退重放；StaffDeck 与交易核心另建两个物理测试数据库并分别迁移到 `20260731_0008`。
- 已拆分 `app.staffdeck_main` 与 `app.transaction_main`。正式运行配置会拒绝缺失的身份服务或 StaffDeck 内部地址。
- 交易域已移除对 `AgentProfile`、`AgentResourceBinding`、`AgentSkillBranch` 与 `AgentSkillBranchVersion` 的直接查询；改走 `/api/internal/v1/staffdeck/*` 契约。
- StaffDeck 不保存交易侧密码副本；用户令牌通过 `/api/internal/v1/identity/resolve` 由交易核心校验。
- 内部调用使用独立 HMAC 服务密钥，并强制忽略宿主机 HTTP 代理，避免内部令牌外送和假性 502。
- Marketplace Skill 安装写入 Outbox；远端调用失败时保留 `pending`，后台线程自动幂等重放。
- 订单文件已支持本地私有目录和 S3/MinIO Provider；下载先过订单/企业 ACL，再签发 5 分钟临时地址。
- 已提供受控 3I 测试种子。生产环境硬拒绝执行，预发/测试也必须传入固定确认短语。
- 跨进程、跨数据库验收已通过：交易登录 → 远程身份校验 → StaffDeck AI 员工列表 → 交易侧远程获取安装目标。

部署与回滚步骤见 `deploy/phase-3i/README.md`。

## 当前阶段约束

- 支付仍为演示 Provider，不发生真实扣款、退款或放款。
- PostgreSQL/MinIO 切换不得通过修改业务断言或降低测试覆盖实现。
- 交易核心和 StaffDeck 分离后只允许使用版本化 API、内部服务身份和 Outbox 事件通信。
- 真实业务记录不得退回前端 fixture、进程内内存数据或只读演示 JSON。
