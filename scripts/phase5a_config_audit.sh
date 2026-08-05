#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
transaction_env="${project_dir}/deploy/phase-3i/transaction.env.example"
staffdeck_env="${project_dir}/deploy/phase-3i/staffdeck.env.example"
nginx_config="${project_dir}/deploy/phase-5a/app.kaigongba.net.split.conf"

assert_contains() {
    local pattern="$1"
    local file="$2"
    if ! grep -Eq "${pattern}" "${file}"; then
        printf 'Required production guard missing: %s (%s)\n' "${pattern}" "${file}" >&2
        exit 1
    fi
}

for env_file in "${transaction_env}" "${staffdeck_env}"; do
    assert_contains '^RUNTIME_ENVIRONMENT=production$' "${env_file}"
    assert_contains '^DATABASE_STARTUP_MODE=validate$' "${env_file}"
    assert_contains '^DEMO_SEED_ENABLED=false$' "${env_file}"
    assert_contains '^MARKETPLACE_SEED_ENABLED=false$' "${env_file}"
    assert_contains '^REDIS_URL=rediss://[^:]+:' "${env_file}"
    assert_contains '^REDIS_KEY_PREFIX=kaigongba:[a-z-]+$' "${env_file}"
    assert_contains '^REDIS_MAX_CONNECTIONS=[0-9]+$' "${env_file}"
done
assert_contains '^ORDER_OBJECT_STORAGE_PROVIDER=s3$' "${transaction_env}"
assert_contains '^HOSTED_SKILL_EXECUTION_ENABLED=false$' "${transaction_env}"
assert_contains '^TRANSACTION_ROLE=api$' "${transaction_env}"
assert_contains '^STAFFDECK_ROLE=api$' "${staffdeck_env}"
assert_contains 'location \^~ /api/internal/ \{ return 404; \}' "${nginx_config}"
assert_contains 'Strict-Transport-Security' "${nginx_config}"
assert_contains 'app.transaction_main:app' \
    "${project_dir}/deploy/phase-5a/kaigongba-transaction.service"
assert_contains 'app.staffdeck_main:app' \
    "${project_dir}/deploy/phase-5a/kaigongba-staffdeck.service"
assert_contains 'app.transaction.outbox_worker' \
    "${project_dir}/deploy/phase-5a/kaigongba-transaction-worker.service"
assert_contains 'TRANSACTION_ROLE=worker' \
    "${project_dir}/deploy/phase-5a/kaigongba-transaction-worker.service"
assert_contains 'app.scheduled_tasks.worker' \
    "${project_dir}/deploy/phase-5a/kaigongba-staffdeck-worker.service"
assert_contains 'STAFFDECK_ROLE=worker' \
    "${project_dir}/deploy/phase-5a/kaigongba-staffdeck-worker.service"
assert_contains 'BACKGROUND_JOBS_ROLE=api' \
    "${project_dir}/deploy/app.kaigongba.net/kaigongba-app.service"
assert_contains 'Requires=.*redis.service' \
    "${project_dir}/deploy/app.kaigongba.net/kaigongba-app.service"
assert_contains 'app.worker_main' \
    "${project_dir}/deploy/app.kaigongba.net/kaigongba-worker.service"
assert_contains 'BACKGROUND_JOBS_ROLE=worker' \
    "${project_dir}/deploy/app.kaigongba.net/kaigongba-worker.service"
assert_contains 'Requires=.*redis.service' \
    "${project_dir}/deploy/app.kaigongba.net/kaigongba-worker.service"
assert_contains '^bind 127\.0\.0\.1 ::1$' \
    "${project_dir}/deploy/phase-5a/redis.conf.template"
assert_contains '^protected-mode yes$' \
    "${project_dir}/deploy/phase-5a/redis.conf.template"
assert_contains '^maxmemory-policy noeviction$' \
    "${project_dir}/deploy/phase-5a/redis.conf.template"
assert_contains '^maxmemory 128mb$' \
    "${project_dir}/deploy/phase-5a/redis.conf.template"
assert_contains '^user default off$' \
    "${project_dir}/deploy/phase-5a/redis-users.acl.template"
assert_contains '\+client\|setname' \
    "${project_dir}/deploy/phase-5a/redis-users.acl.template"
assert_contains '^user kaigongba-backup .*\+sync .*\+psync .*\+replconf$' \
    "${project_dir}/deploy/phase-5a/redis-users.acl.template"
assert_contains '^REDIS_BACKUP_URL=redis://kaigongba-backup:' \
    "${project_dir}/deploy/app.kaigongba.net/backup.env.template"
assert_contains 'EnvironmentFile=-/opt/kaigongba-app/shared/backup.env' \
    "${project_dir}/deploy/app.kaigongba.net/kaigongba-app-backup.service"

if grep -R -E '(APP_SECRET|INTERNAL_SERVICE_SECRET|REDIS_URL)=change-me' \
    "${project_dir}/deploy/phase-3i" "${project_dir}/deploy/phase-5a"; then
    printf 'Unsafe default secret found in production deployment templates.\n' >&2
    exit 1
fi

printf 'Phase 5A production configuration audit passed.\n'
