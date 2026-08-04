#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$project_dir/deploy/phase-3i/compose.infrastructure.yml"

docker compose -f "$compose_file" up -d --wait postgres minio redis
docker compose -f "$compose_file" run --rm minio-init
"$project_dir/scripts/phase3i_prepare_split_databases.sh"

printf 'PostgreSQL: 127.0.0.1:%s\n' "${KGB_POSTGRES_PORT:-55432}"
printf 'MinIO API: 127.0.0.1:%s\n' "${KGB_MINIO_PORT:-59000}"
printf 'MinIO Console: 127.0.0.1:%s\n' "${KGB_MINIO_CONSOLE_PORT:-59001}"
printf 'Redis: 127.0.0.1:%s\n' "${KGB_REDIS_PORT:-56379}"
