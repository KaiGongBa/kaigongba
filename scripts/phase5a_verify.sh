#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${project_dir}/scripts/phase3i_infra_up.sh"

(
    cd "${project_dir}/backend"
    .venv/bin/ruff check \
        app/external_agents \
        app/integrations/staffdeck \
        app/api/external_agents.py \
        app/app_factory.py \
        app/redis_runtime.py \
        app/transaction/outbox_worker.py
    .venv/bin/pytest -q \
        tests/test_external_agent_enrollment_api.py \
        tests/test_staffdeck_internal_api.py \
        tests/test_transaction_outbox_worker.py \
        tests/test_service_runtime.py \
        tests/test_service_entrypoints.py \
        tests/test_database_config.py \
        tests/test_app_readiness.py
)

(
    cd "${project_dir}/frontend-enterprise"
    npm run build
)

"${project_dir}/scripts/phase3i_verify_postgres.sh"
"${project_dir}/scripts/phase3i_verify_minio.sh"
"${project_dir}/scripts/phase5a_verify_redis.sh"
"${project_dir}/scripts/phase3i_verify_split_services.sh"
"${project_dir}/scripts/phase5a_config_audit.sh"
"${project_dir}/scripts/phase5a_verify_load.sh"
"${project_dir}/scripts/phase5a_restore_drill.sh"

printf 'Phase 5A production gate passed. Real payment remains out of scope.\n'
