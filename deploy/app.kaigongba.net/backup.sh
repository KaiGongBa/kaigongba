#!/usr/bin/env bash
set -euo pipefail

backup_root=/opt/kaigongba-app/backups
database_dir=${backup_root}/database
files_dir=${backup_root}/files
backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)

install -d -m 0750 "${database_dir}" "${files_dir}"

pg_dump --format=custom --file="${database_dir}/kgbapp-${backup_stamp}.dump" kgbapp
tar -C /opt/kaigongba-app/shared \
    -czf "${files_dir}/order-objects-${backup_stamp}.tar.gz" \
    order-objects

find "${database_dir}" -type f -name 'kgbapp-*.dump' -mtime +14 -delete
find "${files_dir}" -type f -name 'order-objects-*.tar.gz' -mtime +14 -delete
