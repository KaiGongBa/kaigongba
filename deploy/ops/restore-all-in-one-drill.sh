#!/usr/bin/env bash
set -euo pipefail

: "${KGB_RESTORE_SET:?KGB_RESTORE_SET must point to one backup set}"
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${RESTORE_FILES_DIR:?RESTORE_FILES_DIR is required}"

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
verify_script="${KGB_BACKUP_VERIFY_SCRIPT:-${project_dir}/scripts/ops_backup_verify.py}"
max_age_hours="${KGB_RESTORE_MAX_BACKUP_AGE_HOURS:-720}"
python_runtime="${KGB_PYTHON_RUNTIME:-python3}"

case "${RESTORE_DATABASE_URL}" in
    */*_restore_test|*/*_restore_test\?*) ;;
    *) printf 'Restore database target must end with _restore_test.\n' >&2; exit 2 ;;
esac
case "$(basename "${RESTORE_FILES_DIR}")" in
    *-restore-test) ;;
    *) printf 'RESTORE_FILES_DIR basename must end with -restore-test.\n' >&2; exit 2 ;;
esac
if [[ -e "${RESTORE_FILES_DIR}" ]] && [[ -n "$(find "${RESTORE_FILES_DIR}" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    printf 'Restore files target must be absent or empty: %s\n' "${RESTORE_FILES_DIR}" >&2
    exit 2
fi

"${python_runtime}" "${verify_script}" "${KGB_RESTORE_SET}" --max-age-hours "${max_age_hours}" >/dev/null

database_dump="${KGB_RESTORE_SET}/postgres/kgbapp.dump"
files_archive="${KGB_RESTORE_SET}/files/order-objects.tar.gz"
objects_snapshot="${KGB_RESTORE_SET}/objects/order-objects"
test -f "${database_dump}"
if [[ ! -f "${files_archive}" && ! -d "${objects_snapshot}" ]]; then
    printf 'Backup set contains neither a local archive nor an object snapshot.\n' >&2
    exit 1
fi

pg_restore --clean --if-exists --no-owner --no-acl \
    --dbname="${RESTORE_DATABASE_URL}" "${database_dump}"

alembic_revision="$(psql "${RESTORE_DATABASE_URL}" -Atc 'SELECT version_num FROM alembic_version')"
table_count="$(psql "${RESTORE_DATABASE_URL}" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
if [[ -z "${alembic_revision}" ]] || ! [[ "${table_count}" =~ ^[0-9]+$ ]] || (( table_count < 1 )); then
    printf 'Restored database failed schema verification. revision=%s tables=%s\n' \
        "${alembic_revision:-missing}" "${table_count:-missing}" >&2
    exit 1
fi

install -d -m 0750 "${RESTORE_FILES_DIR}"
if [[ -f "${files_archive}" ]]; then
    tar -C "${RESTORE_FILES_DIR}" --strip-components=1 -xzf "${files_archive}"
else
    cp -a "${objects_snapshot}"/. "${RESTORE_FILES_DIR}"/
fi
restored_file_count="$(find "${RESTORE_FILES_DIR}" -type f | wc -l | tr -d ' ')"

printf 'All-in-one isolated restore drill passed. revision=%s tables=%s files=%s target=%s\n' \
    "${alembic_revision}" "${table_count}" "${restored_file_count}" "${RESTORE_FILES_DIR}"
