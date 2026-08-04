#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
redis_port="${KGB_REDIS_PORT:-56379}"
redis_password="${KGB_REDIS_PASSWORD:-kaigongba-dev-only}"
compose_file="${project_dir}/deploy/phase-3i/compose.infrastructure.yml"

docker compose -f "${compose_file}" exec -T redis redis-cli ping \
    | grep -qx PONG

(
    cd "${project_dir}/backend"
    KGB_REDIS_TEST_URL="redis://:${redis_password}@127.0.0.1:${redis_port}/15" \
        .venv/bin/pytest -q tests/test_redis_runtime.py
)

printf 'Redis shared runtime verification passed.\n'
