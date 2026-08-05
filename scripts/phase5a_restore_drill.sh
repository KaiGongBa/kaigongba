#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${project_dir}/deploy/phase-3i/compose.infrastructure.yml"
postgres_port="${KGB_POSTGRES_PORT:-55432}"
postgres_password="${KGB_POSTGRES_PASSWORD:-kaigongba-dev-only}"
drill_root="${KGB_PHASE5A_DRILL_ROOT:-${project_dir}/.artifacts/phase5a-restore-drills}"
drill_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${drill_root}/${drill_stamp}"
transaction_source="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_transaction_test"
staffdeck_source="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_staffdeck_test"
transaction_restore="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_transaction_restore_test"
staffdeck_restore="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_staffdeck_restore_test"
restore_bucket="kaigongba-order-files-restore-test"

install -d -m 0750 \
    "${backup_dir}/postgres" \
    "${backup_dir}/objects/kaigongba-order-files" \
    "${backup_dir}/redis"

"${project_dir}/scripts/phase3i_prepare_split_databases.sh" >/dev/null
transaction_revision="$(psql "${transaction_source}" -Atc 'SELECT version_num FROM alembic_version')"
staffdeck_revision="$(psql "${staffdeck_source}" -Atc 'SELECT version_num FROM alembic_version')"
transaction_table_count="$(psql "${transaction_source}" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
staffdeck_table_count="$(psql "${staffdeck_source}" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
pg_dump --format=custom --no-owner --no-acl \
    --file="${backup_dir}/postgres/transaction.dump" "${transaction_source}"
pg_dump --format=custom --no-owner --no-acl \
    --file="${backup_dir}/postgres/staffdeck.dump" "${staffdeck_source}"

docker compose -f "${compose_file}" run --rm \
    -v "${backup_dir}/objects:/backup" \
    --entrypoint /bin/sh minio-init -c '
        mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
        mc mirror --overwrite "local/$MINIO_BUCKET" "/backup/$MINIO_BUCKET"
    ' >/dev/null

redis_container="$(docker compose -f "${compose_file}" ps -q redis)"
docker exec "${redis_container}" redis-cli --rdb /data/phase5a-restore-drill.rdb >/dev/null
docker cp "${redis_container}:/data/phase5a-restore-drill.rdb" \
    "${backup_dir}/redis/dump.rdb" >/dev/null

python3 - "${backup_dir}" "${drill_stamp}" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "schemaVersion": 1,
    "profile": "split",
    "backupId": sys.argv[2],
    "createdAt": datetime.now(UTC).isoformat(),
    "source": "phase5a-local-restore-drill",
    "databases": ["postgres/transaction.dump", "postgres/staffdeck.dump"],
    "objectBucket": "kaigongba-order-files",
    "redis": "redis/dump.rdb",
}
(target / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
PY

(
    cd "${backup_dir}"
    if command -v sha256sum >/dev/null 2>&1; then
        find . -type f ! -name SHA256SUMS -print0 \
            | sort -z | xargs -0 sha256sum >SHA256SUMS
    else
        find . -type f ! -name SHA256SUMS -print0 \
            | sort -z | xargs -0 shasum -a 256 >SHA256SUMS
    fi
)

python3 "${project_dir}/scripts/ops_backup_verify.py" \
    "${backup_dir}" --max-age-hours 1 >/dev/null

for database_name in kaigongba_transaction_restore_test kaigongba_staffdeck_restore_test; do
    docker compose -f "${compose_file}" exec -T postgres \
        dropdb --if-exists -U kaigongba "${database_name}"
    docker compose -f "${compose_file}" exec -T postgres \
        createdb -U kaigongba "${database_name}"
done

KGB_RESTORE_SET="${backup_dir}" \
RESTORE_TRANSACTION_DATABASE_URL="${transaction_restore}" \
RESTORE_STAFFDECK_DATABASE_URL="${staffdeck_restore}" \
    "${project_dir}/deploy/phase-5a/restore-drill.sh"

verify_restored_database() {
    local database_name="$1"
    local expected_revision="$2"
    local expected_tables="$3"
    local revision table_count
    revision="$(docker compose -f "${compose_file}" exec -T postgres \
        psql -U kaigongba -d "${database_name}" -Atc 'SELECT version_num FROM alembic_version')"
    table_count="$(docker compose -f "${compose_file}" exec -T postgres \
        psql -U kaigongba -d "${database_name}" -Atc \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
    if [[ "${revision}" != "${expected_revision}" ]] || [[ "${table_count}" != "${expected_tables}" ]]; then
        printf 'Restored database %s verification failed. revision=%s/%s tables=%s/%s\n' \
            "${database_name}" "${revision}" "${expected_revision}" \
            "${table_count}" "${expected_tables}" >&2
        exit 1
    fi
}

verify_restored_database kaigongba_transaction_restore_test \
    "${transaction_revision}" "${transaction_table_count}"
verify_restored_database kaigongba_staffdeck_restore_test \
    "${staffdeck_revision}" "${staffdeck_table_count}"

docker compose -f "${compose_file}" run --rm \
    -e RESTORE_BUCKET="${restore_bucket}" \
    -v "${backup_dir}/objects:/backup:ro" \
    --entrypoint /bin/sh minio-init -c '
        mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
        mc mb --ignore-existing "local/$RESTORE_BUCKET" >/dev/null
        mc rm --recursive --force "local/$RESTORE_BUCKET" >/dev/null 2>&1 || true
        mc mirror --overwrite "/backup/$MINIO_BUCKET" "local/$RESTORE_BUCKET"
        source_count="$(find "/backup/$MINIO_BUCKET" -type f | wc -l | tr -d " ")"
        restore_count="$(mc find "local/$RESTORE_BUCKET" --type f --print | wc -l | tr -d " ")"
        test "$source_count" = "$restore_count"
    ' >/dev/null
docker cp "${backup_dir}/redis/dump.rdb" \
    "${redis_container}:/data/phase5a-restore-drill-verify.rdb" >/dev/null
docker exec "${redis_container}" redis-check-rdb /data/phase5a-restore-drill-verify.rdb \
    | grep -q 'RDB looks OK'
docker exec "${redis_container}" rm -f /data/phase5a-restore-drill-verify.rdb

printf 'Phase 5A isolated restore drill passed. Backup set: %s revisions=%s/%s tables=%s/%s\n' \
    "${backup_dir}" "${transaction_revision}" "${staffdeck_revision}" \
    "${transaction_table_count}" "${staffdeck_table_count}"
