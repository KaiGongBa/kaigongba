#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
artifact_dir="${KGB_PHASE5C_ARTIFACT_DIR:-${project_dir}/.artifacts/phase5c}"
mode="${1:---local}"

if [[ "${mode}" != "--local" && "${mode}" != "--full-infra" ]]; then
    printf 'Usage: %s [--local|--full-infra]\n' "$0" >&2
    exit 2
fi

mkdir -p "${artifact_dir}"
git -C "${project_dir}" diff --check
"${project_dir}/scripts/phase5c_no_new_skips.sh"

python3 -m py_compile \
    "${project_dir}/scripts/phase5c_release_manifest.py" \
    "${project_dir}/scripts/phase5c_smoke.py"

(
    cd "${project_dir}/frontend-enterprise"
    npm test
    npm run build
    npm run i18n:check
    npm run config:check
)

(
    cd "${project_dir}/backend"
    .venv/bin/ruff check app tests
    .venv/bin/pytest -q
)

python3 "${project_dir}/scripts/phase5c_release_manifest.py" \
    --output "${artifact_dir}/release-manifest.json"

if [[ -n "${KGB_PHASE5C_BASE_URL:-}" ]]; then
    KGB_PHASE5C_SMOKE_REPORT="${artifact_dir}/read-only-smoke.json" \
        python3 "${project_dir}/scripts/phase5c_smoke.py"
else
    printf 'Phase 5C pre-release smoke skipped: KGB_PHASE5C_BASE_URL is not set.\n'
fi

if [[ "${mode}" == "--full-infra" ]]; then
    "${project_dir}/scripts/phase5a_verify.sh"
fi

printf 'Phase 5C release-candidate gate passed (%s). Real payment remains disabled.\n' "${mode}"
