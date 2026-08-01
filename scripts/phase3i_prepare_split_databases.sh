#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$project_dir/deploy/phase-3i/compose.infrastructure.yml"
postgres_port="${KGB_POSTGRES_PORT:-55432}"
postgres_password="${KGB_POSTGRES_PASSWORD:-kaigongba-dev-only}"

ensure_database() {
    local database_name="$1"
    local present
    present="$(
        docker compose -f "$compose_file" exec -T postgres \
            psql -U kaigongba -d postgres -Atc \
            "SELECT 1 FROM pg_database WHERE datname = '$database_name'"
    )"
    if [[ "$present" != "1" ]]; then
        docker compose -f "$compose_file" exec -T postgres \
            createdb -U kaigongba "$database_name"
    fi
}

migrate_database() {
    local database_name="$1"
    local database_url
    database_url="postgresql://kaigongba:${postgres_password}@127.0.0.1:${postgres_port}/${database_name}"
    (
        cd "$project_dir/backend"
        DATABASE_URL="$database_url" .venv/bin/python -m app.db.migrate
    )
}

ensure_database kaigongba_staffdeck_test
ensure_database kaigongba_transaction_test
migrate_database kaigongba_staffdeck_test
migrate_database kaigongba_transaction_test

printf 'StaffDeck DB: kaigongba_staffdeck_test\n'
printf 'Transaction DB: kaigongba_transaction_test\n'
