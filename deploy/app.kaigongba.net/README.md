# app.kaigongba.net deployment

This deployment is isolated from the existing `kaigongba.net` website:

- Application files: `/opt/kaigongba-app`
- API service: `kaigongba-app.service`
- API listener: `127.0.0.1:8020`
- PostgreSQL role/database: `kgbapp`
- Nginx vhost: `/etc/nginx/conf.d/app.kaigongba.net.conf`
- Uploaded order files: `/opt/kaigongba-app/shared/order-objects`
- Daily backups: `/opt/kaigongba-app/backups/{database,files}`

This directory describes the currently deployed all-in-one compatibility service.
The reviewed split-service candidate, Redis/runtime requirements and complete disaster
recovery gate live in `deploy/phase-5a/`. Do not copy the split Nginx configuration until
both new readiness endpoints pass on the server.

The web/API process runs with `STAFFDECK_ROLE=api`. StaffDeck channel connector
code and configuration pages remain in the application, but long-running
external channel connectors must be deployed as a separate connector role
after their SQLite-only process supervisors are upgraded for PostgreSQL.

Each release is stored under `/opt/kaigongba-app/releases/<release-id>`. The
`current` symlink selects the active release. Pre-deployment configuration
backups are stored in `/opt/kaigongba-app/backups`.

## Health and logs

```sh
curl --fail https://app.kaigongba.net/api/health
curl --fail https://app.kaigongba.net/api/ready
systemctl status kaigongba-app
journalctl -u kaigongba-app -n 200 --no-pager
systemctl status kaigongba-app-backup.timer
```

## Rollback

Point `current` at the preceding release, restart the API, test Nginx, and
reload it:

```sh
ln -sfn /opt/kaigongba-app/releases/<previous-release-id> /opt/kaigongba-app/current
systemctl restart kaigongba-app
nginx -t
systemctl reload nginx
```

Database migrations must be checked before an application rollback. Restore a
database backup only when a migration is not backward compatible.
