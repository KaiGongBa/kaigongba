#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_ref="${KGB_PHASE5C_BASE_REF:-HEAD}"

if ! git -C "${project_dir}" rev-parse --verify "${base_ref}^{commit}" >/dev/null 2>&1; then
    printf 'Phase 5C skip guard cannot resolve base ref: %s\n' "${base_ref}" >&2
    exit 2
fi

diff_args=(--unified=0 "${base_ref}")
if [[ "${base_ref}" != "HEAD" ]]; then
    diff_args=(--unified=0 "${base_ref}...HEAD")
fi

added_lines="$({
    git -C "${project_dir}" diff "${diff_args[@]}" -- \
        backend/tests frontend-enterprise/src
    git -C "${project_dir}" diff --unified=0 -- \
        backend/tests frontend-enterprise/src
    git -C "${project_dir}" diff --cached --unified=0 -- \
        backend/tests frontend-enterprise/src
    while IFS= read -r path; do
        [[ -z "${path}" ]] || sed 's/^/+/' "${project_dir}/${path}"
    done < <(
        git -C "${project_dir}" ls-files --others --exclude-standard -- \
            backend/tests frontend-enterprise/src
    )
} | sed -n '/^+++ /d; /^+/p')"

if printf '%s\n' "${added_lines}" | grep -E \
    '(it|test|describe)\.skip[[:space:]]*\(|pytest\.skip[[:space:]]*\(|pytest\.mark\.(skip|skipif|xfail)|@pytest\.mark\.(skip|skipif|xfail)' \
    >/dev/null; then
    printf 'Phase 5C gate rejected newly added skipped or xfailed tests:\n%s\n' \
        "$(printf '%s\n' "${added_lines}" | grep -E '(skip|xfail)')" >&2
    exit 1
fi

printf 'Phase 5C skip guard passed (base: %s).\n' "${base_ref}"
