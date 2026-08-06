#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---targeted}"

if [[ "${mode}" != "--targeted" && "${mode}" != "--full" ]]; then
    printf 'Usage: %s [--targeted|--full]\n' "$0" >&2
    exit 2
fi

backend_python="${project_dir}/backend/.venv/bin/python"
backend_pytest="${project_dir}/backend/.venv/bin/pytest"
backend_ruff="${project_dir}/backend/.venv/bin/ruff"

git -C "${project_dir}" diff --check
"${project_dir}/scripts/phase5c_no_new_skips.sh"

"${backend_ruff}" check \
    "${project_dir}/backend/app" \
    "${project_dir}/backend/tests" \
    "${project_dir}/sdk/python/src" \
    "${project_dir}/sdk/python/tests"

if [[ "${mode}" == "--full" ]]; then
    (
        cd "${project_dir}/backend"
        "${backend_pytest}" -q
    )
else
    (
        cd "${project_dir}/backend"
        "${backend_pytest}" -q \
            tests/test_transaction_pretrade_api.py::test_phase5g8_independent_buyer_provider_accounts_complete_transaction \
            tests/test_transaction_pretrade_api.py::test_invitation_outbox_generates_private_draft_without_ai_pricing_or_auto_send \
            tests/test_external_agent_local_simulator.py \
            tests/test_platform_assistant_adaptive_orchestrator.py \
            tests/test_platform_assistant_runtime.py
    )
fi

PYTHONPATH="${project_dir}/sdk/python/src" \
    "${backend_python}" -m pytest "${project_dir}/sdk/python/tests" -q

wheel_dir="$(mktemp -d "${TMPDIR:-/tmp}/kaigongba-agent-wheel.XXXXXX")"
"${backend_python}" -m pip wheel --no-deps --wheel-dir "${wheel_dir}" \
    "${project_dir}/sdk/python" >/dev/null
find "${wheel_dir}" -maxdepth 1 -type f -name '*.whl' -print -quit | grep -q .

(
    cd "${project_dir}/frontend-enterprise"
    if [[ "${mode}" == "--full" ]]; then
        npm test
    else
        npx vitest run \
            src/features/marketplace/DemandCreatePage.test.tsx \
            src/pages/chat/KaiAssistantDrawer.test.tsx \
            src/features/kai-assistant/protocol.v2.test.ts \
            src/features/kai-assistant/components/assistantService.v2.test.ts
    fi
    npm run build
)

printf 'Phase 5G-8 gate passed (%s). Payment remains demo-only.\n' "${mode}"
