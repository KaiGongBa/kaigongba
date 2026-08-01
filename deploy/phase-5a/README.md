# 阶段 5A 生产运行与灾备

本目录只处理非支付生产化。真实支付、分账和结算仍保持关闭，待支付渠道方案单独评审。

## 发布前门禁

1. 两个数据库分别完成不可变备份，且对象存储和 Redis RDB 同属一个时间戳备份集。
2. 在隔离的 `*_restore_test` 数据库和 `*-restore-test` Bucket 完成恢复演练。
3. 运行 `scripts/phase5a_verify.sh`，确认后端回归、前端构建、PostgreSQL 迁移、MinIO、Redis 和拆分服务均通过。
4. `/api/health` 只用于进程存活；负载均衡必须使用 `/api/ready`，只有数据库和 Redis 都可用才返回 200。
5. 公网反向代理必须拒绝 `/api/internal/`，生产只开放交易核心和 StaffDeck 的明确路由。

完整门禁命令：

```bash
./scripts/phase5a_verify.sh
```

该命令会启动本地隔离基础设施，执行后端回归、前端生产构建、迁移升降级、
MinIO/Redis 集成、双服务边界验收、配置审计、只读压力测试和恢复演练。

## 双服务发布

- `kaigongba-transaction.service`：交易核心，监听 `127.0.0.1:8022`。
- `kaigongba-staffdeck.service`：StaffDeck 运行时，监听 `127.0.0.1:8021`。
- `app.kaigongba.net.split.conf`：按 API 所有权分流，并拒绝公网访问内部服务接口。

部署时把 `deploy/phase-3i/transaction.env.example` 和
`deploy/phase-3i/staffdeck.env.example` 分别复制到 shared 目录，替换全部占位符并设置
`0600` 权限。两个进程暂时各使用一个 worker；横向扩容前还需把 StaffDeck 定时任务
拆成独立 worker，避免每个 API 副本都启动调度器。

切换前顺序：备份 → 两库迁移 → 启动双服务 → 分别检查 `/api/ready` → `nginx -t`
→ 切换配置 → 冒烟验收。不要直接覆盖现有单体服务配置。

## 备份

`backup.sh` 需要两个 PostgreSQL URL、Redis URL 和已配置的 `mc` alias。输出包含 SHA-256 清单；默认保留 14 天。

```bash
TRANSACTION_DATABASE_URL=... \
STAFFDECK_DATABASE_URL=... \
REDIS_URL=... \
KGB_OBJECT_STORAGE_ALIAS=prod \
KGB_OBJECT_STORAGE_BUCKET=kaigongba-order-files \
./deploy/phase-5a/backup.sh
```

## 恢复演练

恢复脚本拒绝操作名称不以 `_restore_test` 结尾的数据库，也拒绝非 `-restore-test` Bucket。Redis 备份先做文件完整性检查，不会覆盖正在运行的 Redis。
对象恢复默认用目标 Bucket 去掉 `-restore-test` 后的名称查找源目录；名称不一致时必须显式
传入 `KGB_RESTORE_OBJECT_SOURCE_BUCKET`，防止恢复后的对象 Key 多套一层目录。

本地完整演练：

```bash
./scripts/phase5a_restore_drill.sh
```

演练产物保存在 `.artifacts/phase5a-restore-drills/`（已排除版本管理），便于人工复核。

## 监控和告警基线

- 存活探针：`/api/health`；连续 2 分钟失败触发 P1。
- 就绪探针：`/api/ready`；交易核心会检查 PostgreSQL、Redis 和对象存储，StaffDeck
  检查 PostgreSQL 和 Redis。连续 1 分钟失败应从负载均衡摘除并触发 P1。
- HTTP：5 分钟 5xx 比例超过 2% 或 P95 超过 800 ms 触发 P1。
- Outbox/Webhook：最老 pending 事件超过 5 分钟触发 P1，失败重试率异常触发 P2。
- 外部 Agent：心跳离线、任务超时、Webhook 连续失败已经进入平台运营告警摘要。
- 容量：数据库、对象存储或备份盘使用率超过 75%/85% 分别触发 P2/P1。

应用日志都包含服务名、路径、状态码、耗时和 `X-Request-ID`。反向代理应透传同一
request ID，便于把 Nginx、交易核心、StaffDeck 与任务事件串联起来。

## 回滚

- 应用：切回上一 release symlink，并先确认旧版本与当前 schema 向后兼容。
- 数据库：只有迁移评审明确要求时才逐 revision 回滚；一般应用失败不回滚数据库。
- 对象：先验证新旧对象 SHA-256，再切 Provider；禁止只恢复数据库而忽略文件版本。
- Redis：它不是业务真相源。故障时先恢复 PostgreSQL 服务，再重建缓存和锁；RDB 仅用于缩短恢复时间。

恢复目标：RPO 不超过 24 小时（正式商业化前收紧到 1 小时），RTO 演练目标 60 分钟。

## 明确不在 5A 内

真实支付、平台分账、自动结算、发票与渠道对账均不在本阶段启用。当前支付单和回调
只用于演示业务闭环，后续必须通过独立支付阶段完成持牌渠道评审、签约和生产接入。
