#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
endpoint="${KGB_MINIO_TEST_ENDPOINT:-http://127.0.0.1:59000}"

cd "$project_dir/backend"
KGB_MINIO_TEST_ENDPOINT="$endpoint" .venv/bin/pytest -q tests/test_order_object_storage.py
