#!/usr/bin/env bash
set -euo pipefail

backup_root="${KGB_BACKUP_ROOT:-/opt/kaigongba-app/backups}"
retention_days="${KGB_BACKUP_RETENTION_DAYS:-14}"
database_target="${KGB_DATABASE_TARGET:-kgbapp}"
objects_dir="${KGB_ORDER_OBJECTS_DIR:-/opt/kaigongba-app/shared/order-objects}"
backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
staging_dir="${backup_root}/sets/.${backup_stamp}.partial.$$"
backup_dir="${backup_root}/sets/${backup_stamp}"
completed=0

case "${backup_root}" in
    /|/Users|/home|/root|/opt|/opt/kaigongba-app)
        printf 'KGB_BACKUP_ROOT must be a dedicated backup directory.\n' >&2
        exit 2
        ;;
esac
if ! [[ "${retention_days}" =~ ^[0-9]+$ ]] || (( retention_days < 1 )); then
    printf 'KGB_BACKUP_RETENTION_DAYS must be a positive integer.\n' >&2
    exit 2
fi
if [[ ! -d "${objects_dir}" ]]; then
    printf 'Order object directory does not exist: %s\n' "${objects_dir}" >&2
    exit 2
fi
if [[ -e "${backup_dir}" ]]; then
    printf 'Backup set already exists: %s\n' "${backup_dir}" >&2
    exit 2
fi

for command_name in pg_dump pg_restore tar python3; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'Required backup command is missing: %s\n' "${command_name}" >&2
        exit 2
    fi
done
if [[ -n "${REDIS_BACKUP_URL:-}" ]]; then
    for command_name in redis-cli redis-check-rdb; do
        if ! command -v "${command_name}" >/dev/null 2>&1; then
            printf 'Redis is configured but required backup command is missing: %s\n' \
                "${command_name}" >&2
            exit 2
        fi
    done
fi

mark_failed() {
    if (( completed == 0 )) && [[ -d "${staging_dir}" ]]; then
        printf 'backup failed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${staging_dir}/FAILED"
    fi
}
trap mark_failed EXIT

install -d -m 0750 "${backup_root}/sets" "${staging_dir}/postgres" "${staging_dir}/files"

pg_dump --format=custom --no-owner --no-acl \
    --file="${staging_dir}/postgres/kgbapp.dump" \
    "${database_target}"
pg_restore --list "${staging_dir}/postgres/kgbapp.dump" >/dev/null

tar -C "$(dirname "${objects_dir}")" \
    -czf "${staging_dir}/files/order-objects.tar.gz" \
    "$(basename "${objects_dir}")"
tar -tzf "${staging_dir}/files/order-objects.tar.gz" >/dev/null

redis_enabled=false
if [[ -n "${REDIS_BACKUP_URL:-}" ]]; then
    install -d -m 0750 "${staging_dir}/redis"
    redis-cli -u "${REDIS_BACKUP_URL}" --rdb "${staging_dir}/redis/dump.rdb" >/dev/null
    redis-check-rdb "${staging_dir}/redis/dump.rdb" >/dev/null
    redis_enabled=true
fi

python3 - "${staging_dir}" "${backup_stamp}" "${redis_enabled}" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "schemaVersion": 1,
    "profile": "all-in-one",
    "backupId": sys.argv[2],
    "createdAt": datetime.now(UTC).isoformat(),
    "hostname": os.uname().nodename,
    "database": "postgres/kgbapp.dump",
    "files": "files/order-objects.tar.gz",
}
if sys.argv[3] == "true":
    payload["redis"] = "redis/dump.rdb"
(target / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
PY

(
    cd "${staging_dir}"
    if command -v sha256sum >/dev/null 2>&1; then
        find . -type f ! -name SHA256SUMS ! -name FAILED -print0 \
            | sort -z | xargs -0 sha256sum >SHA256SUMS
    else
        find . -type f ! -name SHA256SUMS ! -name FAILED -print0 \
            | sort -z | xargs -0 shasum -a 256 >SHA256SUMS
    fi
)

chmod 0640 "${staging_dir}/SHA256SUMS" "${staging_dir}/manifest.json" \
    "${staging_dir}/postgres/kgbapp.dump" "${staging_dir}/files/order-objects.tar.gz"
if [[ "${redis_enabled}" == true ]]; then
    chmod 0640 "${staging_dir}/redis/dump.rdb"
fi
mv "${staging_dir}" "${backup_dir}"
ln -sfn "${backup_dir}" "${backup_root}/latest"
completed=1

find "${backup_root}/sets" -mindepth 1 -maxdepth 1 -type d \
    ! -name '.*.partial.*' -mtime "+${retention_days}" -exec rm -rf -- {} +

printf 'Verified all-in-one backup set created: %s\n' "${backup_dir}"
