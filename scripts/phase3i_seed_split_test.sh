#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
postgres_port="${KGB_POSTGRES_PORT:-55432}"
postgres_password="${KGB_POSTGRES_PASSWORD:-kaigongba-dev-only}"
common_url="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}"

seed_target() {
    local target="$1"
    local database_name="$2"
    (
        cd "$project_dir/backend"
        RUNTIME_ENVIRONMENT=test \
        DATABASE_URL="${common_url}/${database_name}" \
        DATABASE_STARTUP_MODE=validate \
        DEMO_SEED_ENABLED=false \
        MARKETPLACE_SEED_ENABLED=false \
        .venv/bin/python -m app.db.phase3i_seed \
            --target "$target" \
            --confirm PHASE-3I-TEST-DATA
    )
}

seed_target staffdeck kaigongba_staffdeck_test
seed_target transaction kaigongba_transaction_test

printf 'Phase 3I split-service acceptance identities seeded.\n'
