#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
database_url="${KGB_POSTGRES_TEST_URL:-postgresql://kaigongba:kaigongba-dev-only@127.0.0.1:55432/kaigongba_test}"

cd "$project_dir/backend"
KGB_POSTGRES_TEST_URL="$database_url" .venv/bin/pytest -q tests/test_postgres_migrations.py
