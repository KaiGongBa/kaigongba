#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_dir="$project_dir/backend"
staffdeck_port="${KGB_STAFFDECK_TEST_PORT:-18001}"
transaction_port="${KGB_TRANSACTION_TEST_PORT:-18002}"
postgres_port="${KGB_POSTGRES_PORT:-55432}"
postgres_password="${KGB_POSTGRES_PASSWORD:-kaigongba-dev-only}"
redis_port="${KGB_REDIS_PORT:-56379}"
redis_password="${KGB_REDIS_PASSWORD:-kaigongba-dev-only}"
redis_url="redis://:${redis_password}@127.0.0.1:${redis_port}/0"
staffdeck_url="http://127.0.0.1:${staffdeck_port}"
transaction_url="http://127.0.0.1:${transaction_port}"
app_secret="phase-3i-shared-app-secret"
internal_secret="phase-3i-internal-service-secret"
run_dir="$(mktemp -d)"
staffdeck_pid=""
transaction_pid=""

cleanup() {
    if [[ -n "$staffdeck_pid" ]]; then
        kill "$staffdeck_pid" 2>/dev/null || true
    fi
    if [[ -n "$transaction_pid" ]]; then
        kill "$transaction_pid" 2>/dev/null || true
    fi
    wait "$staffdeck_pid" "$transaction_pid" 2>/dev/null || true
}
trap cleanup EXIT

wait_for_health() {
    local service_url="$1"
    local attempts=0
    until curl --fail --silent "$service_url/api/health" >/dev/null; do
        attempts=$((attempts + 1))
        if [[ "$attempts" -ge 30 ]]; then
            printf 'Service did not become healthy: %s\n' "$service_url" >&2
            return 1
        fi
        sleep 0.2
    done
}

"$project_dir/scripts/phase3i_prepare_split_databases.sh" >/dev/null
"$project_dir/scripts/phase3i_seed_split_test.sh" >/dev/null

local_identity_count="$(
    docker compose -f "$project_dir/deploy/phase-3i/compose.infrastructure.yml" \
        exec -T postgres psql -U kaigongba -d kaigongba_staffdeck_test -Atc \
        "SELECT count(*) FROM users WHERE id = 'user_phase3i_provider'"
)"
if [[ "$local_identity_count" != "0" ]]; then
    printf 'StaffDeck test DB must not contain the acceptance user identity.\n' >&2
    exit 1
fi

(
    cd "$backend_dir"
    env \
        RUNTIME_ENVIRONMENT=staging \
        DATABASE_URL="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_transaction_test" \
        DATABASE_STARTUP_MODE=validate \
        APP_SECRET="$app_secret" \
        INTERNAL_SERVICE_SECRET="$internal_secret" \
        DEMO_SEED_ENABLED=false \
        MARKETPLACE_SEED_ENABLED=false \
        STAFFDECK_INTERNAL_BASE_URL="$staffdeck_url" \
        REDIS_URL="$redis_url" \
        .venv/bin/uvicorn app.transaction_main:app \
            --host 127.0.0.1 --port "$transaction_port"
) >"$run_dir/transaction.log" 2>&1 &
transaction_pid="$!"

(
    cd "$backend_dir"
    env \
        RUNTIME_ENVIRONMENT=staging \
        DATABASE_URL="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_staffdeck_test" \
        DATABASE_STARTUP_MODE=validate \
        APP_SECRET="$app_secret" \
        INTERNAL_SERVICE_SECRET="$internal_secret" \
        DEMO_SEED_ENABLED=false \
        MARKETPLACE_SEED_ENABLED=false \
        STAFFDECK_ROLE=api \
        IDENTITY_INTERNAL_BASE_URL="$transaction_url" \
        REDIS_URL="$redis_url" \
        .venv/bin/uvicorn app.staffdeck_main:app \
            --host 127.0.0.1 --port "$staffdeck_port"
) >"$run_dir/staffdeck.log" 2>&1 &
staffdeck_pid="$!"

if ! wait_for_health "$transaction_url" || ! wait_for_health "$staffdeck_url"; then
    tail -n 80 "$run_dir/transaction.log" >&2 || true
    tail -n 80 "$run_dir/staffdeck.log" >&2 || true
    exit 1
fi

access_token="$(
    curl --fail --silent --show-error \
        -H 'Content-Type: application/json' \
        -d '{"tenant_id":"tenant_phase3i","username":"phase3i_provider","password":"Phase3I!2026"}' \
        "$transaction_url/api/auth/login" | jq -r '.token'
)"

curl --fail --silent --show-error \
    -H "Authorization: Bearer ${access_token}" \
    "$staffdeck_url/api/enterprise/agents?tenant_id=tenant_phase3i" \
    | jq -e 'any(.[]; .id == "agent_phase3i_delivery")' >/dev/null

curl --fail --silent --show-error \
    -H "Authorization: Bearer ${access_token}" \
    "$transaction_url/api/marketplace/install-targets?organizationId=org_phase3i_provider" \
    | jq -e 'any(.[]; .id == "agent_phase3i_delivery")' >/dev/null

printf 'Phase 3I split-service identity and StaffDeck boundary verified.\n'
printf 'Logs: %s\n' "$run_dir"
