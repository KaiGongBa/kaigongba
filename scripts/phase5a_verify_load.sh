#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_dir="${project_dir}/backend"
transaction_port="${KGB_PHASE5A_LOAD_PORT:-18003}"
postgres_port="${KGB_POSTGRES_PORT:-55432}"
postgres_password="${KGB_POSTGRES_PASSWORD:-kaigongba-dev-only}"
redis_port="${KGB_REDIS_PORT:-56379}"
redis_password="${KGB_REDIS_PASSWORD:-kaigongba-dev-only}"
service_url="http://127.0.0.1:${transaction_port}"
run_dir="$(mktemp -d "${TMPDIR:-/tmp}/kaigongba-phase5a-load.XXXXXX")"
service_pid=""

cleanup() {
    if [[ -n "${service_pid}" ]]; then
        kill "${service_pid}" 2>/dev/null || true
        wait "${service_pid}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

"${project_dir}/scripts/phase3i_prepare_split_databases.sh" >/dev/null

(
    cd "${backend_dir}"
    env \
        RUNTIME_ENVIRONMENT=staging \
        DATABASE_URL="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/kaigongba_transaction_test" \
        DATABASE_STARTUP_MODE=validate \
        APP_SECRET=phase-5a-load-test-secret \
        INTERNAL_SERVICE_SECRET=phase-5a-internal-service-secret \
        DEMO_SEED_ENABLED=false \
        MARKETPLACE_SEED_ENABLED=false \
        STAFFDECK_INTERNAL_BASE_URL=http://127.0.0.1:18001 \
        REDIS_URL="redis://kaigongba-dev:${redis_password}@127.0.0.1:${redis_port}/0" \
        ORDER_OBJECT_STORAGE_PROVIDER=s3 \
        ORDER_OBJECT_STORAGE_ENDPOINT_URL=http://127.0.0.1:59000 \
        ORDER_OBJECT_STORAGE_ACCESS_KEY=kaigongba \
        ORDER_OBJECT_STORAGE_SECRET_KEY=kaigongba-dev-only \
        ORDER_OBJECT_STORAGE_BUCKET=kaigongba-order-files \
        .venv/bin/uvicorn app.transaction_main:app \
            --host 127.0.0.1 --port "${transaction_port}"
) >"${run_dir}/transaction.log" 2>&1 &
service_pid="$!"

for _ in $(seq 1 40); do
    if curl --fail --silent "${service_url}/api/ready" >/dev/null; then
        break
    fi
    sleep 0.25
done
if ! curl --fail --silent "${service_url}/api/ready" >/dev/null; then
    tail -n 100 "${run_dir}/transaction.log" >&2
    exit 1
fi

"${project_dir}/scripts/phase5a_load_test.py" \
    --base-url "${service_url}" \
    --path /api/ready \
    --warmup "${KGB_PHASE5A_LOAD_WARMUP:-10}" \
    --requests "${KGB_PHASE5A_LOAD_REQUESTS:-500}" \
    --concurrency "${KGB_PHASE5A_LOAD_CONCURRENCY:-20}" \
    --p95-ms "${KGB_PHASE5A_LOAD_P95_MS:-800}"

printf 'Phase 5A read-only load verification passed. Logs: %s\n' "${run_dir}"
