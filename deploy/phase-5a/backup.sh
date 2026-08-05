#!/usr/bin/env bash
set -euo pipefail

backup_root="${KGB_BACKUP_ROOT:-/var/backups/kaigongba}"
retention_days="${KGB_BACKUP_RETENTION_DAYS:-14}"
backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${backup_root}/sets/${backup_stamp}"
completed=0
python_runtime="${KGB_PYTHON_RUNTIME:-python3}"

case "${backup_root}" in
    /|/Users|/home|/root|"${HOME}")
        printf 'KGB_BACKUP_ROOT must be a dedicated backup directory.\n' >&2
        exit 2
        ;;
esac
if ! [[ "${retention_days}" =~ ^[0-9]+$ ]] || (( retention_days < 1 )); then
    printf 'KGB_BACKUP_RETENTION_DAYS must be a positive integer.\n' >&2
    exit 2
fi

: "${TRANSACTION_DATABASE_URL:?TRANSACTION_DATABASE_URL is required}"
: "${STAFFDECK_DATABASE_URL:?STAFFDECK_DATABASE_URL is required}"
: "${REDIS_URL:?REDIS_URL is required}"
: "${KGB_OBJECT_STORAGE_ALIAS:?KGB_OBJECT_STORAGE_ALIAS is required}"
: "${KGB_OBJECT_STORAGE_BUCKET:?KGB_OBJECT_STORAGE_BUCKET is required}"

install -d -m 0750 \
    "${backup_dir}/postgres" \
    "${backup_dir}/objects/${KGB_OBJECT_STORAGE_BUCKET}" \
    "${backup_dir}/redis"

mark_failed() {
    if (( completed == 0 )) && [[ -d "${backup_dir}" ]]; then
        printf 'backup failed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${backup_dir}/FAILED"
    fi
}
trap mark_failed EXIT

pg_dump --format=custom --no-owner --no-acl \
    --file="${backup_dir}/postgres/transaction.dump" \
    "${TRANSACTION_DATABASE_URL}"
pg_dump --format=custom --no-owner --no-acl \
    --file="${backup_dir}/postgres/staffdeck.dump" \
    "${STAFFDECK_DATABASE_URL}"
pg_restore --list "${backup_dir}/postgres/transaction.dump" >/dev/null
pg_restore --list "${backup_dir}/postgres/staffdeck.dump" >/dev/null

mc mirror --overwrite \
    "${KGB_OBJECT_STORAGE_ALIAS}/${KGB_OBJECT_STORAGE_BUCKET}" \
    "${backup_dir}/objects/${KGB_OBJECT_STORAGE_BUCKET}"

redis-cli -u "${REDIS_URL}" --rdb "${backup_dir}/redis/dump.rdb" >/dev/null
if command -v redis-check-rdb >/dev/null 2>&1; then
    redis-check-rdb "${backup_dir}/redis/dump.rdb" >/dev/null
fi

"${python_runtime}" - "${backup_dir}" "${backup_stamp}" "${KGB_OBJECT_STORAGE_BUCKET}" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "schemaVersion": 1,
    "profile": "split",
    "backupId": sys.argv[2],
    "createdAt": datetime.now(UTC).isoformat(),
    "hostname": os.uname().nodename,
    "databases": ["postgres/transaction.dump", "postgres/staffdeck.dump"],
    "objectBucket": sys.argv[3],
    "redis": "redis/dump.rdb",
}
(target / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
PY

(
    cd "${backup_dir}"
    if command -v sha256sum >/dev/null 2>&1; then
        find . -type f ! -name SHA256SUMS -print0 \
            | sort -z \
            | xargs -0 sha256sum >SHA256SUMS
    else
        find . -type f ! -name SHA256SUMS -print0 \
            | sort -z \
            | xargs -0 shasum -a 256 >SHA256SUMS
    fi
)

chmod 0640 "${backup_dir}/SHA256SUMS" "${backup_dir}/manifest.json" \
    "${backup_dir}/postgres/transaction.dump" "${backup_dir}/postgres/staffdeck.dump" \
    "${backup_dir}/redis/dump.rdb"
ln -sfn "${backup_dir}" "${backup_root}/latest"
completed=1
find "${backup_root}/sets" -mindepth 1 -maxdepth 1 -type d -mtime "+${retention_days}" -exec rm -rf -- {} +

printf 'Backup set created: %s\n' "${backup_dir}"
