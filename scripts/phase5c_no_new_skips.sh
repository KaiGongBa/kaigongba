#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_ref="${KGB_PHASE5C_BASE_REF:-HEAD}"
# The skip guard was introduced after the production-infrastructure tests had
# already established their explicit environment skips.  The first PR that
# brings the guard to main must therefore compare from the guard epoch instead
# of treating those pre-existing markers as newly added.  Once main contains
# the epoch, normal PRs continue to compare against their actual base ref.
guard_epoch="a7e9c5d7d69d1374d64224bb7fe8b5211b95bad9"

if ! git -C "${project_dir}" rev-parse --verify "${base_ref}^{commit}" >/dev/null 2>&1; then
    printf 'Phase 5C skip guard cannot resolve base ref: %s\n' "${base_ref}" >&2
    exit 2
fi

effective_base_ref="${base_ref}"
if [[ "${base_ref}" != "HEAD" ]] \
    && git -C "${project_dir}" merge-base --is-ancestor "${base_ref}" "${guard_epoch}" \
    && git -C "${project_dir}" merge-base --is-ancestor "${guard_epoch}" HEAD; then
    effective_base_ref="${guard_epoch}"
fi

diff_args=(--unified=0 "${effective_base_ref}")
if [[ "${effective_base_ref}" != "HEAD" ]]; then
    diff_args=(--unified=0 "${effective_base_ref}...HEAD")
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

printf 'Phase 5C skip guard passed (base: %s; effective: %s).\n' \
    "${base_ref}" "${effective_base_ref}"
