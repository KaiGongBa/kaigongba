#!/usr/bin/env bash
set -euo pipefail

: "${KGB_RESTORE_SET:?KGB_RESTORE_SET must point to one backup set directory}"
: "${RESTORE_TRANSACTION_DATABASE_URL:?RESTORE_TRANSACTION_DATABASE_URL is required}"
: "${RESTORE_STAFFDECK_DATABASE_URL:?RESTORE_STAFFDECK_DATABASE_URL is required}"

case "${RESTORE_TRANSACTION_DATABASE_URL}" in
    */*_restore_test|*/*_restore_test\?*) ;;
    *) printf 'Transaction restore target must end with _restore_test.\n' >&2; exit 2 ;;
esac
case "${RESTORE_STAFFDECK_DATABASE_URL}" in
    */*_restore_test|*/*_restore_test\?*) ;;
    *) printf 'StaffDeck restore target must end with _restore_test.\n' >&2; exit 2 ;;
esac

test -f "${KGB_RESTORE_SET}/SHA256SUMS"
test ! -f "${KGB_RESTORE_SET}/FAILED"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "${KGB_RESTORE_SET}" && sha256sum --check SHA256SUMS)
else
    (cd "${KGB_RESTORE_SET}" && shasum -a 256 --check SHA256SUMS)
fi

pg_restore --clean --if-exists --no-owner --no-acl \
    --dbname="${RESTORE_TRANSACTION_DATABASE_URL}" \
    "${KGB_RESTORE_SET}/postgres/transaction.dump"
pg_restore --clean --if-exists --no-owner --no-acl \
    --dbname="${RESTORE_STAFFDECK_DATABASE_URL}" \
    "${KGB_RESTORE_SET}/postgres/staffdeck.dump"

for restore_url in "${RESTORE_TRANSACTION_DATABASE_URL}" "${RESTORE_STAFFDECK_DATABASE_URL}"; do
    revision="$(psql "${restore_url}" -Atc 'SELECT version_num FROM alembic_version')"
    table_count="$(psql "${restore_url}" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
    if [[ -z "${revision}" ]] || ! [[ "${table_count}" =~ ^[0-9]+$ ]] || (( table_count < 1 )); then
        printf 'Restored database failed schema verification. revision=%s tables=%s\n' \
            "${revision:-missing}" "${table_count:-missing}" >&2
        exit 1
    fi
done

if command -v redis-check-rdb >/dev/null 2>&1; then
    redis-check-rdb "${KGB_RESTORE_SET}/redis/dump.rdb"
fi

if [[ -n "${KGB_RESTORE_OBJECT_ALIAS:-}" || -n "${KGB_RESTORE_OBJECT_BUCKET:-}" ]]; then
    : "${KGB_RESTORE_OBJECT_ALIAS:?Both restore object variables are required}"
    : "${KGB_RESTORE_OBJECT_BUCKET:?Both restore object variables are required}"
    case "${KGB_RESTORE_OBJECT_BUCKET}" in
        *-restore-test) ;;
        *) printf 'Object restore bucket must end with -restore-test.\n' >&2; exit 2 ;;
    esac
    source_bucket="${KGB_RESTORE_OBJECT_SOURCE_BUCKET:-${KGB_RESTORE_OBJECT_BUCKET%-restore-test}}"
    if [[ -z "${source_bucket}" || ! -d "${KGB_RESTORE_SET}/objects/${source_bucket}" ]]; then
        printf 'Object backup source bucket directory is missing: %s\n' "${source_bucket}" >&2
        exit 2
    fi
    mc mirror --overwrite \
        "${KGB_RESTORE_SET}/objects/${source_bucket}" \
        "${KGB_RESTORE_OBJECT_ALIAS}/${KGB_RESTORE_OBJECT_BUCKET}"
fi

printf 'Restore drill completed for isolated *_restore_test targets.\n'
