# 开工吧运维可验证性工具

本目录补齐当前 `app.kaigongba.net` 单体兼容部署和 Phase 5A 双服务候选的只读预检、
成套备份校验、隔离恢复演练、日志检查和基础压力基线。所有恢复脚本只接受名称明确以
`_restore_test` / `-restore-test` 结尾的隔离目标。

## 1. 公网只读预检

```bash
python3 scripts/ops_preflight.py \
  --base-url https://app.kaigongba.net \
  --profile compatibility \
  --output .artifacts/ops/preflight.json
```

`compatibility` 允许当前 Redis `not_configured`，但会保留警告；单体API加独立任务进程使用
`--profile combined-worker`，正式切换双服务使用 `--profile split`。后两者把全部就绪依赖、
响应 Request ID 和 Redis 备份设为硬门禁。

## 2. 当前单体成套备份

把 `backup-all-in-one.sh` 安装为 `/opt/kaigongba-app/bin/backup.sh` 前先人工审查差异。
脚本将数据库、订单文件、元数据和 SHA-256 清单写入同一个时间戳目录，完成格式检查后
才原子更新 `latest`。当隔离的 `backup.env` 配置 `REDIS_BACKUP_URL` 时，备份服务会同时
生成并强制校验 `redis/dump.rdb`；API 的 `REDIS_URL` 不需要、也不应拥有复制权限。

```bash
KGB_DATABASE_TARGET=kgbapp \
KGB_BACKUP_ROOT=/opt/kaigongba-app/backups \
KGB_ORDER_OBJECTS_DIR=/opt/kaigongba-app/shared/order-objects \
REDIS_BACKUP_URL=redis://kaigongba-backup:...@127.0.0.1:6379/0 \
./deploy/ops/backup-all-in-one.sh

python3 scripts/ops_backup_verify.py \
  /opt/kaigongba-app/backups/latest \
  --max-age-hours 30
```

## 3. 单体隔离恢复演练

先创建空数据库 `kgbapp_restore_test`。脚本不会创建、删除或覆盖非测试数据库，也拒绝向
非空文件目录恢复。

```bash
KGB_RESTORE_SET=/opt/kaigongba-app/backups/latest \
RESTORE_DATABASE_URL=postgresql:///kgbapp_restore_test \
RESTORE_FILES_DIR=/var/tmp/kgbapp-order-files-restore-test \
./deploy/ops/restore-all-in-one-drill.sh
```

## 4. 主机只读审计

在服务器上运行；它检查 systemd、Nginx语法、公网探针、最近成套备份、磁盘和错误日志，
不重启服务、不改配置。

```bash
KGB_PROJECT_DIR=/opt/kaigongba-app/current \
KGB_OPS_PROFILE=compatibility \
./deploy/ops/host-audit.sh
```

单体API加独立 combined worker 的过渡环境改用：

```bash
KGB_OPS_PROFILE=combined-worker \
KGB_COMBINED_WORKER_UNIT=kaigongba-worker \
./deploy/ops/host-audit.sh
```

## 5. 基础只读压力测试

```bash
KGB_LOAD_TEST_CONFIRM=RUN_READ_ONLY_LOAD_TEST \
python3 scripts/phase5a_load_test.py \
  --base-url https://app.kaigongba.net \
  --path /api/ready \
  --warmup 10 --requests 100 --concurrency 5 \
  --p95-ms 800 --output .artifacts/ops/load.json
```

生产仅允许对 `/api/health`、`/api/ready` 等无副作用GET接口执行基础基线。正式容量测试
必须在独立压测环境完成，并由云监控同时记录CPU、内存、数据库连接、Redis和对象存储。

## 仍需外部配置

- 异地、加密、不可变备份目标及生命周期策略。
- 云监控、日志采集、告警联系人和夜间升级路径。
- Phase 5A 所需正式 Redis、对象存储和双PostgreSQL实例。
- 恢复演练记录归档、RPO/RTO负责人签字与定期计划。
