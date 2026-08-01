#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$project_dir/deploy/phase-3i/compose.infrastructure.yml"

docker compose -f "$compose_file" ps
