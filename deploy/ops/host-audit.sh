#!/usr/bin/env bash
set -euo pipefail

profile="${KGB_OPS_PROFILE:-compatibility}"
public_url="${KGB_PUBLIC_URL:-https://app.kaigongba.net}"
backup_root="${KGB_BACKUP_ROOT:-/opt/kaigongba-app/backups}"
project_dir="${KGB_PROJECT_DIR:-/opt/kaigongba-app/current}"
max_backup_age_hours="${KGB_MAX_BACKUP_AGE_HOURS:-30}"
disk_warning_percent="${KGB_DISK_WARNING_PERCENT:-75}"
log_since="${KGB_LOG_SINCE:-24 hours ago}"
python_runtime="${KGB_PYTHON_RUNTIME:-python3}"

case "${profile}" in
    compatibility)
        units=(kaigongba-app kaigongba-app-backup.timer)
        ;;
    combined-worker)
        units=(kaigongba-app "${KGB_COMBINED_WORKER_UNIT:-kaigongba-worker}" kaigongba-app-backup.timer)
        ;;
    split)
        units=(
            kaigongba-transaction
            kaigongba-transaction-worker
            kaigongba-staffdeck
            kaigongba-staffdeck-worker
        )
        ;;
    *) printf 'KGB_OPS_PROFILE must be compatibility, combined-worker or split.\n' >&2; exit 2 ;;
esac

for unit in "${units[@]}"; do
    systemctl is-active --quiet "${unit}" || {
        printf 'Inactive required unit: %s\n' "${unit}" >&2
        exit 1
    }
done

nginx -t >/dev/null
"${python_runtime}" "${project_dir}/scripts/ops_preflight.py" \
    --base-url "${public_url}" --profile "${profile}" >/dev/null

latest="$(readlink -f "${backup_root}/latest" 2>/dev/null || true)"
if [[ -z "${latest}" || ! -d "${latest}" ]]; then
    printf 'No complete latest backup set found under %s.\n' "${backup_root}" >&2
    exit 1
fi
backup_verify_args=("${latest}" --max-age-hours "${max_backup_age_hours}")
if [[ "${profile}" != compatibility ]]; then
    backup_verify_args+=(--require-redis)
fi
"${python_runtime}" "${project_dir}/scripts/ops_backup_verify.py" "${backup_verify_args[@]}" >/dev/null

disk_use="$(df -P "${backup_root}" | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')"
if ! [[ "${disk_use}" =~ ^[0-9]+$ ]] || (( disk_use >= disk_warning_percent )); then
    printf 'Backup filesystem utilization is above threshold: %s%%\n' "${disk_use:-unknown}" >&2
    exit 1
fi

for unit in "${units[@]}"; do
    errors="$(journalctl -u "${unit}" --since "${log_since}" -p err --no-pager --output=cat | wc -l | tr -d ' ')"
    printf 'unit=%s errors_since=%q error_lines=%s\n' "${unit}" "${log_since}" "${errors}"
done
printf 'Host audit passed. profile=%s backup=%s disk_use=%s%%\n' "${profile}" "${latest}" "${disk_use}"
