# app.kaigongba.net deployment

This deployment is isolated from the existing `kaigongba.net` website:

- Application files: `/opt/kaigongba-app`
- API service: `kaigongba-app.service`
- Background service: `kaigongba-worker.service`
- API listener: `127.0.0.1:8020`
- PostgreSQL role/database: `kgbapp`
- Nginx vhost: `/etc/nginx/conf.d/app.kaigongba.net.conf`
- Uploaded order files: `/opt/kaigongba-app/shared/order-objects`
- Daily backup sets: `/opt/kaigongba-app/backups/sets/<UTC timestamp>`

This directory describes the currently deployed all-in-one compatibility service.
The reviewed split-service candidate, Redis/runtime requirements and complete disaster
recovery gate live in `deploy/phase-5a/`. Do not copy the split Nginx configuration until
both new readiness endpoints pass on the server.

The web/API unit forces `BACKGROUND_JOBS_ROLE=api`; the worker unit forces
`BACKGROUND_JOBS_ROLE=worker` and runs scheduled tasks plus transaction Outbox
against the same compatibility database. The source default remains
`BACKGROUND_JOBS_ROLE=embedded`, so local development and rollback to the old
single-process unit keep their historical behavior. Never start the new worker
until the API unit has disabled its embedded workers, or both processes will
poll the same queues unnecessarily.

The web/API process runs with `STAFFDECK_ROLE=api`. StaffDeck channel connector
code and configuration pages remain in the application, but long-running
external channel connectors must be deployed as a separate connector role
after their SQLite-only process supervisors are upgraded for PostgreSQL.

Each release is stored under `/opt/kaigongba-app/releases/<release-id>`. The
`current` symlink selects the active release. Pre-deployment configuration
backups are stored in `/opt/kaigongba-app/backups`.

Release directories must be traversable by the Nginx worker while their source
files remain owned by `kgbapp`. After extracting a release, set the release
directory itself to mode `0711`, keep frontend directories at least `0755` and
frontend files at least `0644`, then verify the entrypoint as the Nginx user
before switching `current`:

```sh
chmod 0711 /opt/kaigongba-app/releases/<release-id>
find /opt/kaigongba-app/releases/<release-id>/frontend -type d -exec chmod 0755 {} +
find /opt/kaigongba-app/releases/<release-id>/frontend -type f -exec chmod 0644 {} +
runuser -u nginx -- test -r /opt/kaigongba-app/releases/<release-id>/frontend/index.html
```

`deploy/ops/host-audit.sh` repeats this access check so a release with an
unreadable SPA entrypoint cannot pass the production gate.

## Health and logs

```sh
curl --fail https://app.kaigongba.net/api/health
curl --fail https://app.kaigongba.net/api/ready
systemctl status kaigongba-app
journalctl -u kaigongba-worker -n 200 --no-pager
journalctl -u kaigongba-app -n 200 --no-pager
systemctl status kaigongba-app-backup.timer
```

The backup timer loads an isolated `backup.env`. It creates a paired PostgreSQL
+ order-file set and, after `REDIS_BACKUP_URL` is configured, also requires a
verified Redis RDB in the same set. Run `scripts/ops_backup_verify.py`
against `/opt/kaigongba-app/backups/latest` after every backup and use the
isolated restore procedure in `deploy/ops/README.md` for drills.

## Rollback

Point `current` at the preceding release, restart the API, test Nginx, and
reload it:

```sh
ln -sfn /opt/kaigongba-app/releases/<previous-release-id> /opt/kaigongba-app/current
systemctl restart kaigongba-worker kaigongba-app
nginx -t
systemctl reload nginx
```

Database migrations must be checked before an application rollback. Restore a
database backup only when a migration is not backward compatible.

To roll back only the process split, stop and disable `kaigongba-worker`, remove
the `BACKGROUND_JOBS_ROLE=api` override from the API unit, reload systemd and
restart `kaigongba-app`. Business schema and records are unchanged by this
runtime split.

## Redis single-host transition

The Alibaba Cloud Linux 3 single-host deployment must install Redis 6.2 or later
as a loopback-only service before switching the application environment to the
ACL URL in `app.env.template`.

1. Copy `deploy/phase-5a/redis.conf.template` to the Redis configuration path.
2. Copy `deploy/phase-5a/redis-users.acl.template` to
   `/etc/redis/kaigongba-users.acl`, keep the `kaigongba-app` application user
   and the isolated `kaigongba-backup` user, replace their placeholders with
   distinct random secrets of at least 32 bytes, and set both files to
   `root:redis` with mode `0640`.
3. Confirm Redis binds only `127.0.0.1`/`::1`, the default user is disabled,
   AOF is enabled, `maxmemory` is `128mb` for the current 1.8 GiB ECS, and
   `maxmemory-policy` is `noeviction`.
4. Set the same ACL username/password in `REDIS_URL`, restart Redis, run
   `redis-cli --user kaigongba-app --askpass PING`, and only then restart the app.
5. `/api/ready` must return Redis `ok`; startup intentionally fails if PING,
   read/write, or Lua lock primitives are unavailable.
6. Store the backup-only URL in `/opt/kaigongba-app/shared/backup.env` using
   `backup.env.template`. Do not expose its replication permission to the API
   or Worker environment.

For a later remote/shared Redis, use `rediss://` with certificate and hostname
verification. A remote plaintext `redis://` URL is rejected in staging and
production.
